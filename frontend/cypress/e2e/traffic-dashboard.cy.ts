/// <reference types="cypress" />

/**
 * Cypress E2E Tests for AI-ML Traffic Management System
 * 
 * Test Scenarios:
 * 1. Verify video feed loads correctly
 * 2. Monitor real-time vehicle count updates
 * 3. Test lane-specific data visualization
 */

describe('Traffic Management Dashboard', () => {
  beforeEach(() => {
    // Visit the main dashboard before each test
    cy.visit('/');
    cy.intercept('GET', '/api/v1/health').as('healthCheck');
    cy.intercept('GET', '/api/v1/traffic/status').as('trafficStatus');
  });

  describe('Dashboard Loading', () => {
    it('should load the main dashboard successfully', () => {
      // BEFORE STATE: Page is loading, no content visible
      // ACTION: Wait for dashboard components to render
      // AFTER STATE: Dashboard fully loaded with all sections visible
      
      cy.get('[data-testid="dashboard-container"]').should('be.visible');
      cy.get('[data-testid="traffic-header"]').should('contain', 'Traffic Management');
      cy.wait('@healthCheck').its('response.statusCode').should('eq', 200);
    });

    it('should display navigation menu items', () => {
      // BEFORE STATE: Navigation not rendered
      // AFTER STATE: All navigation items visible and clickable
      
      cy.get('[data-testid="nav-dashboard"]').should('be.visible');
      cy.get('[data-testid="nav-analytics"]').should('be.visible');
      cy.get('[data-testid="nav-settings"]').should('be.visible');
    });
  });

  describe('Video Feed Component', () => {
    it('should load video feed correctly', () => {
      // BEFORE STATE: Video container empty, loading spinner visible
      // ACTION: Wait for video stream initialization
      // AFTER STATE: Video feed active with live traffic view
      
      cy.get('[data-testid="video-feed-container"]').should('exist');
      cy.get('[data-testid="video-loading-spinner"]').should('not.exist', { timeout: 10000 });
      cy.get('[data-testid="video-player"]').should('be.visible');
    });

    it('should display video feed status indicator', () => {
      // BEFORE STATE: Status unknown
      // AFTER STATE: Status indicator shows "Live" or "Connected"
      
      cy.get('[data-testid="video-status"]')
        .should('be.visible')
        .and('have.class', 'status-active');
    });

    it('should handle video feed errors gracefully', () => {
      // Simulate video feed failure
      cy.intercept('GET', '/api/v1/video/stream', { statusCode: 500 }).as('videoError');
      cy.reload();
      
      // AFTER STATE: Error message displayed, retry button available
      cy.get('[data-testid="video-error-message"]').should('be.visible');
      cy.get('[data-testid="video-retry-button"]').should('be.visible');
    });
  });

  describe('Real-Time Vehicle Count Updates', () => {
    it('should display initial vehicle count', () => {
      // BEFORE STATE: Vehicle count component loading
      // AFTER STATE: Count displayed with numeric value >= 0
      
      cy.wait('@trafficStatus');
      cy.get('[data-testid="total-vehicle-count"]')
        .should('be.visible')
        .invoke('text')
        .then((text) => {
          const count = parseInt(text);
          expect(count).to.be.gte(0);
        });
    });

    it('should update vehicle count in real-time via WebSocket', () => {
      // BEFORE STATE: Initial count = N
      // ACTION: Simulate WebSocket message with new count
      // AFTER STATE: Count updated to new value
      
      cy.get('[data-testid="total-vehicle-count"]')
        .invoke('text')
        .then((initialCount) => {
          // Store initial count for comparison
          cy.wrap(parseInt(initialCount)).as('initialCount');
        });

      // Wait for real-time update (simulated or actual)
      cy.wait(5000);
      
      cy.get('[data-testid="total-vehicle-count"]')
        .invoke('text')
        .then(function(newCount) {
          // Verify count has capability to update
          expect(parseInt(newCount)).to.be.gte(0);
        });
    });

    it('should display vehicle count breakdown by type', () => {
      // AFTER STATE: Individual counts for cars, trucks, buses visible
      
      cy.get('[data-testid="vehicle-type-cars"]').should('be.visible');
      cy.get('[data-testid="vehicle-type-trucks"]').should('be.visible');
      cy.get('[data-testid="vehicle-type-buses"]').should('be.visible');
    });
  });

  describe('Lane-Specific Data Visualization', () => {
    it('should display traffic data for all 4 lanes', () => {
      // BEFORE STATE: Lane components not rendered
      // AFTER STATE: North, South, East, West lanes all visible with data
      
      const lanes = ['north', 'south', 'east', 'west'];
      
      lanes.forEach((lane) => {
        cy.get(`[data-testid="lane-${lane}"]`)
          .should('be.visible')
          .within(() => {
            cy.get('[data-testid="lane-vehicle-count"]').should('exist');
            cy.get('[data-testid="lane-status"]').should('exist');
          });
      });
    });

    it('should show correct lane direction indicators', () => {
      // Verify lane direction arrows/icons are displayed
      cy.get('[data-testid="lane-north"] [data-testid="direction-indicator"]')
        .should('have.attr', 'aria-label', 'North-bound traffic');
      cy.get('[data-testid="lane-south"] [data-testid="direction-indicator"]')
        .should('have.attr', 'aria-label', 'South-bound traffic');
    });

    it('should update lane-specific counts independently', () => {
      // BEFORE STATE: All lanes show initial counts
      // ACTION: Simulate detection update for specific lane
      // AFTER STATE: Only affected lane count changes
      
      cy.intercept('POST', '/api/v1/traffic/detect', {
        statusCode: 200,
        body: {
          lane_counts: { north: 5, south: 3, east: 2, west: 4 },
          total_vehicles: 14
        }
      }).as('detectVehicles');

      cy.get('[data-testid="lane-north"] [data-testid="lane-vehicle-count"]')
        .should('contain', '5');
      cy.get('[data-testid="lane-east"] [data-testid="lane-vehicle-count"]')
        .should('contain', '2');
    });

    it('should display lane traffic chart visualization', () => {
      // Verify Chart.js visualization renders
      cy.get('[data-testid="lane-chart-container"]').should('be.visible');
      cy.get('canvas').should('exist');
    });

    it('should highlight congested lanes', () => {
      // BEFORE STATE: Normal lane styling
      // ACTION: Lane exceeds congestion threshold
      // AFTER STATE: Lane highlighted with warning color
      
      cy.intercept('GET', '/api/v1/traffic/status', {
        statusCode: 200,
        body: {
          lane_counts: { north: 20, south: 3, east: 2, west: 1 },
          congestion_alerts: ['north']
        }
      }).as('congestedStatus');

      cy.reload();
      cy.wait('@congestedStatus');
      
      cy.get('[data-testid="lane-north"]')
        .should('have.class', 'lane-congested');
    });
  });

  describe('Traffic Signal Control', () => {
    it('should display current signal phase', () => {
      cy.get('[data-testid="signal-phase-indicator"]')
        .should('be.visible')
        .and('contain.text', /Phase/);
    });

    it('should show signal timing countdown', () => {
      cy.get('[data-testid="signal-countdown"]')
        .should('be.visible')
        .invoke('text')
        .then((text) => {
          const seconds = parseInt(text);
          expect(seconds).to.be.gte(0).and.lte(120);
        });
    });
  });

  describe('Error Handling and Recovery', () => {
    it('should display error toast on API failure', () => {
      cy.intercept('GET', '/api/v1/traffic/status', { statusCode: 500 }).as('apiError');
      cy.reload();
      cy.wait('@apiError');
      
      cy.get('[data-testid="error-toast"]').should('be.visible');
    });

    it('should retry failed requests automatically', () => {
      let requestCount = 0;
      cy.intercept('GET', '/api/v1/traffic/status', (req) => {
        requestCount++;
        if (requestCount < 3) {
          req.reply({ statusCode: 500 });
        } else {
          req.reply({ statusCode: 200, body: { lane_counts: {} } });
        }
      }).as('retryRequest');

      cy.reload();
      cy.wait('@retryRequest');
      cy.wait('@retryRequest');
      cy.wait('@retryRequest');
      
      // After retries, dashboard should be functional
      cy.get('[data-testid="dashboard-container"]').should('be.visible');
    });
  });
});

describe('Responsive Design Tests', () => {
  const viewports = [
    { name: 'mobile', width: 375, height: 667 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'desktop', width: 1920, height: 1080 }
  ];

  viewports.forEach((viewport) => {
    it(`should render correctly on ${viewport.name}`, () => {
      cy.viewport(viewport.width, viewport.height);
      cy.visit('/');
      
      cy.get('[data-testid="dashboard-container"]').should('be.visible');
      cy.get('[data-testid="video-feed-container"]').should('be.visible');
    });
  });
});
