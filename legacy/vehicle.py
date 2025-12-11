# vehicle.py

import pygame
import random
import os
import config

class Vehicle(pygame.sprite.Sprite):
    """
    Represents a single vehicle in the simulation.
    It handles its own movement, appearance, and starting position.
    """
    VEHICLE_TYPES = ['car', 'bus', 'truck', 'rickshaw', 'bike']
    
    # Define movement boundaries to stop vehicles before the intersection
    STOP_LINES = {'right': 620, 'left': 780, 'up': 450, 'down': 350}
    
    # Define where vehicles should disappear after crossing the intersection
    DISAPPEAR_LINES = {'right': -200, 'left': 1600, 'up': -200, 'down': 1000}

    def __init__(self, direction):
        """
        Initializes a vehicle sprite.

        Args:
            direction (str): The direction the vehicle is traveling from ('right', 'left', 'up', 'down').
        """
        super().__init__()
        
        self.direction = direction
        self.type = random.choice(self.VEHICLE_TYPES)
        self.speed = random.randint(10, 20)
        
        # Load the vehicle's image
        image_path = os.path.join(config.ASSETS_DIR, self.direction, f"{self.type}.png")
        try:
            self.image = pygame.image.load(image_path).convert_alpha()
        except pygame.error:
            print(f"Warning: Could not load image for {self.type} in direction {self.direction}. Using a placeholder.")
            self.image = pygame.Surface((30, 60)) # Placeholder size
            self.image.fill((255, 0, 0)) # Red placeholder

        # Set the starting position based on direction
        self.rect = self.image.get_rect()
        self._set_initial_position()

    def _set_initial_position(self):
        """
        Sets the vehicle's starting coordinates off-screen based on its direction.
        """
        if self.direction == 'right':
            self.rect.x = config.SIM_WIDTH + random.randint(0, 300)
            self.rect.y = 370
        elif self.direction == 'left':
            self.rect.x = -200 - random.randint(0, 300)
            self.rect.y = 430
        elif self.direction == 'up':
            self.rect.x = 720
            self.rect.y = -200 - random.randint(0, 300)
        elif self.direction == 'down':
            self.rect.x = 660
            self.rect.y = config.SIM_HEIGHT + random.randint(0, 300)

    def move(self, is_green):
        """
        Moves the vehicle based on its direction and the state of the traffic light.

        Args:
            is_green (bool): True if the traffic light for this vehicle's lane is green.
        """
        stop_line = self.STOP_LINES[self.direction]
        disappear_line = self.DISAPPEAR_LINES[self.direction]

        if self.direction == 'right':
            # Move left if the light is green or if the vehicle is already past the stop line
            if is_green or self.rect.x < stop_line:
                self.rect.x -= self.speed
            # Reset position if it has gone off-screen
            if self.rect.x < disappear_line:
                self.rect.x = config.SIM_WIDTH + random.randint(0, 300)
        
        elif self.direction == 'left':
            if is_green or self.rect.x > stop_line:
                self.rect.x += self.speed
            if self.rect.x > disappear_line:
                self.rect.x = -200 - random.randint(0, 300)
        
        elif self.direction == 'up':
            if is_green or self.rect.y > stop_line:
                self.rect.y += self.speed
            if self.rect.y > disappear_line:
                self.rect.y = -200 - random.randint(0, 300)

        elif self.direction == 'down':
            if is_green or self.rect.y < stop_line:
                self.rect.y -= self.speed
            if self.rect.y < disappear_line:
                self.rect.y = config.SIM_HEIGHT + random.randint(0, 300)
