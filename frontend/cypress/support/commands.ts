/// <reference types="cypress" />

// Custom Cypress commands for AI Traffic Management System

Cypress.Commands.add('loginAsAdmin', () => {
  cy.visit('/admin/login');
  cy.get('[data-testid="email-input"]').type('admin@traffic.local');
  cy.get('[data-testid="password-input"]').type('SecureAdminPass123!');
  cy.get('[data-testid="login-submit"]').click();
  cy.url().should('include', '/admin/dashboard');
});

Cypress.Commands.add('waitForDashboard', () => {
  cy.get('[data-testid="dashboard-container"]', { timeout: 15000 }).should('be.visible');
  cy.get('[data-testid="video-feed-container"]').should('be.visible');
  cy.get('[data-testid="lane-display"]').should('be.visible');
});

// API interception helpers
Cypress.Commands.add('mockTrafficStatus', (laneData: Record<string, number>) => {
  cy.intercept('GET', '/api/v1/traffic/status', {
    statusCode: 200,
    body: {
      lane_counts: laneData,
      total_vehicles: Object.values(laneData).reduce((a, b) => a + b, 0),
      timestamp: new Date().toISOString()
    }
  }).as('trafficStatus');
});

Cypress.Commands.add('mockDetectionResult', (vehicleCount: number) => {
  cy.intercept('POST', '/api/v1/traffic/detect', {
    statusCode: 200,
    body: {
      total_vehicles: vehicleCount,
      detected_vehicles: [],
      processing_time: 0.15,
      image_path: '/output_images/test_output.jpg'
    }
  }).as('detectVehicles');
});

// Extend Cypress Chainable interface
declare global {
  namespace Cypress {
    interface Chainable {
      mockTrafficStatus(laneData: Record<string, number>): Chainable<null>;
      mockDetectionResult(vehicleCount: number): Chainable<null>;
    }
  }
}
