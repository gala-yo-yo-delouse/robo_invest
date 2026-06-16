import { defineBackend } from '@aws-amplify/backend';
import { Duration, RemovalPolicy } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { auth } from './auth/resource';
import { data } from './data/resource';

const backend = defineBackend({
  auth,
  data,
});

// ── Single admin only: no public self-signup. Create the user via the CLI. ──
backend.auth.resources.cfnResources.cfnUserPool.adminCreateUserConfig = {
  allowAdminCreateUserOnly: true,
};

// ── Compute/state stack (the serverless trading stack) ──────────────────────
const stack = backend.createStack('RobotradeCompute');

// Environment selector (set ROBOTRADE_ENV at deploy time; default dev).
//   dev  → paper account, legacy unsuffixed names (so the dev stack is
//          untouched by this change), schedule enabled.
//   prod → live account, -prod- names for full isolation, schedule starts
//          DISABLED so it places no real orders until explicitly enabled.
const ENV = process.env.ROBOTRADE_ENV ?? 'dev';
const SFX = ENV === 'dev' ? '' : `-${ENV}`;
const ALPACA_ENV = ENV === 'prod' ? 'live' : 'paper';
const SCHEDULE_ENABLED = ENV !== 'prod';

// Single-table state store: watermarks / ledger / config, one item each.
const stateTable = new dynamodb.Table(stack, 'StateTable', {
  tableName: `robotrade${SFX}-state`,
  partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: RemovalPolicy.RETAIN, // never drop trading state on teardown
  pointInTimeRecovery: true,
});

// Alpaca credentials live in user-owned secrets, one per environment:
//   robotrade/alpaca-paper  and  robotrade/alpaca-live
// The Lambdas pick one via ALPACA_ENV below — flip paper↔live without touching
// secret values. The secrets are NOT managed by CDK (so they survive
// teardown and the user edits them in the console); we only grant read access
// to the namespace. dev reads robotrade/alpaca-paper, prod robotrade/alpaca-live
// (selected by ALPACA_ENV, derived from ENV above).

// Prebuilt, Docker-free deployment package (scripts/build_lambda.sh).
const code = lambda.Code.fromAsset(
  new URL('../build/lambda_package', import.meta.url).pathname
);

const commonEnv = {
  STORAGE_BACKEND: 'dynamodb',
  STATE_TABLE: stateTable.tableName,
  ALPACA_ENV,
};

const sharedProps = {
  runtime: lambda.Runtime.PYTHON_3_13,
  architecture: lambda.Architecture.ARM_64,
  code,
  memorySize: 1024, // headroom for the pandas import on cold start
  environment: commonEnv,
};

// Trading Lambda — one evaluate+execute cycle, fired by EventBridge.
const tradingFn = new lambda.Function(stack, 'TradingFn', {
  ...sharedProps,
  functionName: `robotrade${SFX}-trading`,
  handler: 'trading_handler.handler',
  timeout: Duration.minutes(2),
});

// Query Lambda — frontend reads/writes, referenced by name from data/resource.ts.
const queryFn = new lambda.Function(stack, 'QueryFn', {
  ...sharedProps,
  functionName: `robotrade${SFX}-query`,
  handler: 'query_handler.handler',
  timeout: Duration.minutes(1),
});

// Permissions.
for (const fn of [tradingFn, queryFn]) {
  stateTable.grantReadWriteData(fn);
  // Read any robotrade/* secret (alpaca-paper, alpaca-live, telegram),
  // regardless of the random suffix Secrets Manager appends to the ARN.
  fn.addToRolePolicy(
    new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [
        `arn:aws:secretsmanager:${stack.region}:${stack.account}:secret:robotrade/*`,
      ],
    })
  );
}

// Let AppSync invoke the query function (it's referenced as an external fn).
queryFn.grantInvoke(new iam.ServicePrincipal('appsync.amazonaws.com'));

// The data stack references robotrade-query by name, so the function must
// exist first. Force that ordering explicitly.
backend.data.resources.graphqlApi.node.addDependency(queryFn);

// ── Schedule: every 5 min, Mon–Fri, 13:00–21:55 UTC. The window brackets US
// market hours across DST; the handler re-checks Alpaca's clock and no-ops
// when the market is actually closed (holidays, early closes). ──
new events.Rule(stack, 'TradingSchedule', {
  ruleName: `robotrade${SFX}-trading-schedule`,
  enabled: SCHEDULE_ENABLED, // prod starts disabled
  schedule: events.Schedule.expression('cron(0/5 13-21 ? * MON-FRI *)'),
  targets: [new targets.LambdaFunction(tradingFn)],
});
