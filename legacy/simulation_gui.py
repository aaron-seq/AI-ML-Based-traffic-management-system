# simulation_gui.py

import pygame
import os
import config

class SimulationGUI:
    """
    Handles the graphical user interface of the traffic simulation using Pygame.
    This class is responsible for drawing all elements to the screen.
    """
    def __init__(self):
        """
        Initializes the Pygame window and loads all necessary image assets.
        """
        pygame.init()
        self.screen = pygame.display.set_mode((config.SIM_WIDTH, config.SIM_HEIGHT))
        pygame.display.set_caption("AI Traffic Management Simulation")
        
        # Load assets
        self.assets = self._load_assets()

    def _load_assets(self):
        """
        Loads all images required for the simulation from the assets directory.
        """
        assets = {}
        try:
            # Load background and signal images
            assets['intersection'] = pygame.image.load(os.path.join(config.ASSETS_DIR, 'intersection.jpg')).convert()
            assets['signals'] = {
                'red': pygame.image.load(os.path.join(config.ASSETS_DIR, 'signals', 'red.png')).convert_alpha(),
                'yellow': pygame.image.load(os.path.join(config.ASSETS_DIR, 'signals', 'yellow.png')).convert_alpha(),
                'green': pygame.image.load(os.path.join(config.ASSETS_DIR, 'signals', 'green.png')).convert_alpha()
            }
        except pygame.error as e:
            print(f"Error loading assets: {e}")
            print("Please ensure the 'images' directory and all required assets are present.")
            pygame.quit()
            exit()
        return assets

    def draw(self, simulation_state):
        """
        Draws the entire simulation state to the screen.

        Args:
            simulation_state (dict): A dictionary containing the current state of signals
                                     and vehicle sprites.
        """
        # Draw the background
        self.screen.blit(self.assets['intersection'], (0, 0))
        
        # Draw the traffic signals
        self._draw_signals(simulation_state['signals'])
        
        # Draw all vehicle sprites
        simulation_state['vehicles'].draw(self.screen)
        
        # Update the display
        pygame.display.flip()

    def _draw_signals(self, signal_states):
        """
        Draws the traffic light signals on the screen based on their current state.
        """
        # Define positions for each traffic signal on the screen
        signal_positions = {
            'right': (config.SIM_WIDTH - 150, 50),
            'left': (50, config.SIM_HEIGHT - 150),
            'up': (50, 50),
            'down': (config.SIM_WIDTH - 150, config.SIM_HEIGHT - 150)
        }
        
        for lane, color in signal_states.items():
            self.screen.blit(self.assets['signals'][color], signal_positions[lane])

    def run_game_loop(self, traffic_manager, arduino_comm):
        """
        The main Pygame event loop.

        Args:
            traffic_manager (TrafficManager): The instance managing simulation logic.
            arduino_comm (ArduinoConnector): The instance for Arduino communication.
        """
        running = True
        clock = pygame.time.Clock()

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
            
            # Update the core simulation logic
            traffic_manager.update()
            
            # Get the latest state from the manager
            current_state = traffic_manager.get_simulation_state()
            
            # Send signal state to Arduino if enabled
            if config.ENABLE_ARDUINO and arduino_comm:
                arduino_comm.send_signal_state(current_state['signals'])
            
            # Render the current state
            self.draw(current_state)
            
            # Cap the frame rate
            clock.tick(30) # 30 frames per second
            
        pygame.quit()

