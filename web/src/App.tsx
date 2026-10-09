import { Spin } from 'antd';

import AuthScreen from './components/auth/AuthScreen';
import Workspace from './components/layout/Workspace';
import { useAuth } from './hooks/useAuth';

export default function App() {
  const { ready, identity } = useAuth();

  if (!ready) {
    return (
      <div
        style={{
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  return identity ? <Workspace /> : <AuthScreen />;
}