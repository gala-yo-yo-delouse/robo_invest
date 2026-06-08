import { type ClientSchema, a, defineData } from '@aws-amplify/backend';

// Match the env-scoped function name created in backend.ts (dev keeps the
// legacy unsuffixed name; prod is robotrade-prod-query).
const ENV = process.env.ROBOTRADE_ENV ?? 'dev';
const QUERY_FN = ENV === 'dev' ? 'robotrade-query' : `robotrade-${ENV}-query`;

/**
 * Data layer for the trading dashboard.
 *
 * There is no Amplify-managed model here — all reads/writes flow through the
 * Python query Lambda (robotrade-query), which reuses the bot's own strategy
 * engine. Each field below is a custom query/mutation resolved by that
 * function (referenced by name; the function itself is created in backend.ts).
 * Everything requires an authenticated Cognito user (the single admin).
 */
const schema = a.schema({
  // Live reads (computed fresh from Alpaca on each call).
  getPortfolio: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),

  getSignals: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),

  getProfiles: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),

  getStatus: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),

  // Settings: read + write (the editable config in DynamoDB).
  getSettings: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),

  saveSettings: a
    .mutation()
    .arguments({ settings: a.json() })
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function(QUERY_FN)),
});

export type Schema = ClientSchema<typeof schema>;

export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'userPool',
  },
});
