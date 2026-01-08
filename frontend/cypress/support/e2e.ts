// Cypress E2E support file
// This file runs before every spec file

/// <reference types="cypress" />

// Import custom commands
import './commands';

// Global hooks
beforeEach(() => {
  // Reset database state if needed
  cy.intercept('GET', '/api/v1/**').as('apiRequest');
});

// Handle uncaught exceptions
Cypress.on('uncaught:exception', (err, runnable) => {
  // Return false to prevent Cypress from failing the test
  // for known non-critical errors
  if (err.message.includes('ResizeObserver')) {
    return false;
  }
  return true;
});

// Add custom commands type definitions
declare global {
  namespace Cypress {
    interface Chainable {
      /**
       * Custom command to login as admin
       * @example cy.loginAsAdmin()
       */
      loginAsAdmin(): Chainable<void>;
      
      /**
       * Custom command to wait for dashboard to load
       * @example cy.waitForDashboard()
       */
      waitForDashboard(): Chainable<void>;
    }
  }
}
