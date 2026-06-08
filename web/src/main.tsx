import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { Amplify } from 'aws-amplify';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';

// Backend config written by `ampx sandbox --outputs-out-dir web`.
import outputs from '../amplify_outputs.json';

Amplify.configure(outputs);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/* Single admin: self-signup is disabled in the backend, so only the
        admin user (created via the CLI) can sign in. hideSignUp removes the
        unusable sign-up tab. */}
    <Authenticator hideSignUp>
      {({ signOut, user }) => <App signOut={signOut} username={user?.signInDetails?.loginId} />}
    </Authenticator>
  </React.StrictMode>
);
