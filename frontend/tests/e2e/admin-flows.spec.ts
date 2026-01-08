import { test, expect, Page, BrowserContext } from '@playwright/test';

/**
 * Playwright E2E Tests for AI-ML Traffic Management System
 * 
 * Test Scenarios:
 * 1. Admin authentication flows (Chromium, Firefox, WebKit)
 * 2. Intersection configuration persistence
 * 3. Emergency vehicle priority activation
 */

test.describe('Admin Authentication Flows', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin/login');
  });

  test('should display login form correctly', async ({ page }) => {
    // BEFORE STATE: Login page loading
    // AFTER STATE: Form with email, password fields and submit button visible
    
    await expect(page.getByTestId('login-form')).toBeVisible();
    await expect(page.getByTestId('email-input')).toBeVisible();
    await expect(page.getByTestId('password-input')).toBeVisible();
    await expect(page.getByTestId('login-submit')).toBeVisible();
  });

  test('should authenticate admin user successfully', async ({ page }) => {
    // BEFORE STATE: User not authenticated, no session token
    // ACTION: Enter valid credentials and submit
    // AFTER STATE: Redirected to admin dashboard, session established
    
    await page.getByTestId('email-input').fill('admin@traffic.local');
    await page.getByTestId('password-input').fill('SecureAdminPass123!');
    await page.getByTestId('login-submit').click();

    // Wait for redirect to admin dashboard
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await expect(page.getByTestId('admin-welcome-message')).toBeVisible();
    
    // Verify session token is stored
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find(c => c.name === 'session_token');
    expect(sessionCookie).toBeDefined();
  });

  test('should reject invalid credentials', async ({ page }) => {
    // BEFORE STATE: Login form displayed
    // ACTION: Enter invalid credentials
    // AFTER STATE: Error message displayed, form cleared
    
    await page.getByTestId('email-input').fill('invalid@test.com');
    await page.getByTestId('password-input').fill('wrongpassword');
    await page.getByTestId('login-submit').click();

    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toContainText('Invalid credentials');
    await expect(page).toHaveURL(/\/admin\/login/);
  });

  test('should handle logout correctly', async ({ page }) => {
    // First login
    await page.getByTestId('email-input').fill('admin@traffic.local');
    await page.getByTestId('password-input').fill('SecureAdminPass123!');
    await page.getByTestId('login-submit').click();
    await expect(page).toHaveURL(/\/admin\/dashboard/);

    // BEFORE STATE: User authenticated, session active
    // ACTION: Click logout button
    // AFTER STATE: Session cleared, redirected to login
    
    await page.getByTestId('logout-button').click();
    await expect(page).toHaveURL(/\/admin\/login/);
    
    // Verify session is cleared
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find(c => c.name === 'session_token');
    expect(sessionCookie).toBeUndefined();
  });

  test('should persist session across page reloads', async ({ page }) => {
    // Login first
    await page.getByTestId('email-input').fill('admin@traffic.local');
    await page.getByTestId('password-input').fill('SecureAdminPass123!');
    await page.getByTestId('login-submit').click();
    await expect(page).toHaveURL(/\/admin\/dashboard/);

    // BEFORE STATE: Authenticated session
    // ACTION: Reload page
    // AFTER STATE: Still authenticated, no login required
    
    await page.reload();
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await expect(page.getByTestId('admin-welcome-message')).toBeVisible();
  });
});

test.describe('Intersection Configuration Persistence', () => {
  test.beforeEach(async ({ page }) => {
    // Login as admin first
    await page.goto('/admin/login');
    await page.getByTestId('email-input').fill('admin@traffic.local');
    await page.getByTestId('password-input').fill('SecureAdminPass123!');
    await page.getByTestId('login-submit').click();
    await expect(page).toHaveURL(/\/admin\/dashboard/);
  });

  test('should load intersection configuration page', async ({ page }) => {
    await page.goto('/admin/intersections');
    
    await expect(page.getByTestId('intersection-config-panel')).toBeVisible();
    await expect(page.getByTestId('intersection-list')).toBeVisible();
  });

  test('should create new intersection configuration', async ({ page }) => {
    // BEFORE STATE: No intersection with ID "INT-TEST-001"
    // ACTION: Create new intersection with specified parameters
    // AFTER STATE: Intersection created and visible in list
    
    await page.goto('/admin/intersections');
    await page.getByTestId('add-intersection-button').click();

    // Fill intersection form
    await page.getByTestId('intersection-id-input').fill('INT-TEST-001');
    await page.getByTestId('intersection-name-input').fill('Test Intersection North');
    await page.getByTestId('intersection-lat-input').fill('40.7128');
    await page.getByTestId('intersection-lng-input').fill('-74.0060');
    
    // Configure lane counts
    await page.getByTestId('lanes-north-input').fill('3');
    await page.getByTestId('lanes-south-input').fill('3');
    await page.getByTestId('lanes-east-input').fill('2');
    await page.getByTestId('lanes-west-input').fill('2');

    // Save configuration
    await page.getByTestId('save-intersection-button').click();
    
    // Verify creation
    await expect(page.getByTestId('success-toast')).toBeVisible();
    await expect(page.getByText('INT-TEST-001')).toBeVisible();
  });

  test('should update intersection timing settings', async ({ page }) => {
    // BEFORE STATE: Intersection has default timing (30s green, 5s yellow)
    // ACTION: Update timing to custom values
    // AFTER STATE: New timing values persisted and displayed
    
    await page.goto('/admin/intersections');
    await page.getByTestId('intersection-INT-001').click();
    await page.getByTestId('timing-tab').click();

    // Record original values
    const originalGreenTime = await page.getByTestId('green-time-input').inputValue();
    
    // Update timing
    await page.getByTestId('green-time-input').clear();
    await page.getByTestId('green-time-input').fill('45');
    await page.getByTestId('yellow-time-input').clear();
    await page.getByTestId('yellow-time-input').fill('4');
    await page.getByTestId('min-green-input').fill('15');
    await page.getByTestId('max-green-input').fill('60');
    
    await page.getByTestId('save-timing-button').click();
    await expect(page.getByTestId('success-toast')).toBeVisible();

    // Verify persistence by reloading
    await page.reload();
    await page.getByTestId('intersection-INT-001').click();
    await page.getByTestId('timing-tab').click();
    
    await expect(page.getByTestId('green-time-input')).toHaveValue('45');
    await expect(page.getByTestId('yellow-time-input')).toHaveValue('4');
  });

  test('should delete intersection configuration', async ({ page }) => {
    // BEFORE STATE: Intersection "INT-DELETE-TEST" exists
    // ACTION: Delete the intersection
    // AFTER STATE: Intersection removed from list
    
    await page.goto('/admin/intersections');
    
    // Create intersection to delete
    await page.getByTestId('add-intersection-button').click();
    await page.getByTestId('intersection-id-input').fill('INT-DELETE-TEST');
    await page.getByTestId('intersection-name-input').fill('To Be Deleted');
    await page.getByTestId('intersection-lat-input').fill('40.7128');
    await page.getByTestId('intersection-lng-input').fill('-74.0060');
    await page.getByTestId('save-intersection-button').click();
    await expect(page.getByText('INT-DELETE-TEST')).toBeVisible();

    // Delete intersection
    await page.getByTestId('intersection-INT-DELETE-TEST').click();
    await page.getByTestId('delete-intersection-button').click();
    await page.getByTestId('confirm-delete-button').click();

    await expect(page.getByTestId('success-toast')).toBeVisible();
    await expect(page.getByText('INT-DELETE-TEST')).not.toBeVisible();
  });
});

test.describe('Emergency Vehicle Priority Activation', () => {
  test.beforeEach(async ({ page }) => {
    // Login as admin
    await page.goto('/admin/login');
    await page.getByTestId('email-input').fill('admin@traffic.local');
    await page.getByTestId('password-input').fill('SecureAdminPass123!');
    await page.getByTestId('login-submit').click();
    await page.goto('/admin/emergency');
  });

  test('should display emergency control panel', async ({ page }) => {
    await expect(page.getByTestId('emergency-control-panel')).toBeVisible();
    await expect(page.getByTestId('emergency-status')).toBeVisible();
    await expect(page.getByTestId('activate-emergency-button')).toBeVisible();
  });

  test('should activate emergency vehicle priority mode', async ({ page }) => {
    // BEFORE STATE: Normal traffic mode, no emergency override
    // ACTION: Activate emergency priority for specific lane
    // AFTER STATE: Emergency mode active, affected signals show priority
    
    await page.getByTestId('emergency-direction-select').selectOption('north');
    await page.getByTestId('emergency-type-select').selectOption('ambulance');
    await page.getByTestId('activate-emergency-button').click();

    // Verify emergency mode activation
    await expect(page.getByTestId('emergency-status')).toContainText('ACTIVE');
    await expect(page.getByTestId('emergency-status')).toHaveClass(/emergency-active/);
    
    // Verify affected signals
    await expect(page.getByTestId('signal-north-status')).toContainText('GREEN');
    await expect(page.getByTestId('signal-east-status')).toContainText('RED');
    await expect(page.getByTestId('signal-west-status')).toContainText('RED');
  });

  test('should deactivate emergency mode', async ({ page }) => {
    // First activate emergency mode
    await page.getByTestId('emergency-direction-select').selectOption('south');
    await page.getByTestId('activate-emergency-button').click();
    await expect(page.getByTestId('emergency-status')).toContainText('ACTIVE');

    // BEFORE STATE: Emergency mode active
    // ACTION: Deactivate emergency mode
    // AFTER STATE: Normal traffic mode resumed
    
    await page.getByTestId('deactivate-emergency-button').click();
    
    await expect(page.getByTestId('emergency-status')).toContainText('INACTIVE');
    await expect(page.getByTestId('emergency-status')).not.toHaveClass(/emergency-active/);
  });

  test('should log emergency events to audit trail', async ({ page }) => {
    // Activate then deactivate emergency
    await page.getByTestId('emergency-direction-select').selectOption('east');
    await page.getByTestId('emergency-type-select').selectOption('fire_truck');
    await page.getByTestId('activate-emergency-button').click();
    await page.waitForTimeout(1000);
    await page.getByTestId('deactivate-emergency-button').click();

    // Navigate to audit log
    await page.getByTestId('audit-log-tab').click();
    
    // AFTER STATE: Audit log shows emergency activation and deactivation events
    await expect(page.getByTestId('audit-log-list')).toBeVisible();
    await expect(page.getByText('EMERGENCY_ACTIVATED')).toBeVisible();
    await expect(page.getByText('EMERGENCY_DEACTIVATED')).toBeVisible();
    await expect(page.getByText('fire_truck')).toBeVisible();
  });

  test('should handle concurrent emergency requests', async ({ page }) => {
    // Activate emergency on one direction
    await page.getByTestId('emergency-direction-select').selectOption('north');
    await page.getByTestId('activate-emergency-button').click();
    await expect(page.getByTestId('emergency-status')).toContainText('ACTIVE');

    // Attempt to activate another emergency
    await page.getByTestId('emergency-direction-select').selectOption('south');
    await page.getByTestId('activate-emergency-button').click();

    // Should show warning about existing emergency
    await expect(page.getByTestId('emergency-conflict-warning')).toBeVisible();
  });
});

// Cross-browser test configuration
test.describe('Cross-Browser Compatibility', () => {
  test('should render correctly in current browser', async ({ page, browserName }) => {
    await page.goto('/');
    
    // Take screenshot for visual comparison
    await page.screenshot({ 
      path: `screenshots/dashboard-${browserName}.png`,
      fullPage: true 
    });
    
    await expect(page.getByTestId('dashboard-container')).toBeVisible();
    
    // Log browser-specific info
    console.log(`Testing on: ${browserName}`);
  });
});
