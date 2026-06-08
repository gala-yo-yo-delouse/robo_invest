import { type ClientSchema, a, defineData } from '@aws-amplify/backend';

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
    .handler(a.handler.function('robotrade-query')),

  getSignals: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function('robotrade-query')),

  getProfiles: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function('robotrade-query')),

  getStatus: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function('robotrade-query')),

  // Settings: read + write (the editable config in DynamoDB).
  getSettings: a
    .query()
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function('robotrade-query')),

  saveSettings: a
    .mutation()
    .arguments({ settings: a.json() })
    .returns(a.json())
    .authorization((allow) => [allow.authenticated()])
    .handler(a.handler.function('robotrade-query')),
});

export type Schema = ClientSchema<typeof schema>;

export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'userPool',
  },
});
