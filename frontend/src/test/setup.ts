import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Cleanup después de cada test
afterEach(() => {
  cleanup();
});
