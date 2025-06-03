#!/usr/bin/env python3
"""
Visualization example for Wire EDM Learning Environment.

This example demonstrates how to use the pygame visualization
to see the Wire EDM process in real-time.

Note: Requires pygame to be installed:
    pip install pygame
"""

import numpy as np

try:
    import pygame
except ImportError:
    print("This example requires pygame. Install it with: pip install pygame")
    exit(1)

from wedm import WireEDMEnv, EnvironmentConfig


def main():
    print("=== Wire EDM Visualization Example ===\n")

    # Create environment with visualization enabled
    config = EnvironmentConfig(
        workpiece_height=15.0,
        wire_diameter=0.25,
        target_cutting_distance=500.0,  # Shorter distance for demo
    )

    # Note: render_mode="human" enables pygame visualization
    env = WireEDMEnv(
        config=config, render_mode="human", mechanics_control_mode="position"
    )

    # Reset environment
    obs, info = env.reset()
    print("Environment initialized. Close the pygame window to exit.\n")

    # Control parameters
    action = {
        "servo": np.array([0.2]),  # Moderate feed rate
        "generator_control": {
            "target_voltage": np.array([80.0]),
            "current_mode": np.array([8]),  # I8 - moderate current
            "ON_time": np.array([3.0]),
            "OFF_time": np.array([50.0]),
        },
    }

    # Run simulation
    step_count = 0
    running = True
    clock = pygame.time.Clock()

    print("Running simulation with visualization...")
    print("Press ESC or close window to exit\n")

    while running:
        # Handle pygame events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        # Step environment
        obs, reward, terminated, truncated, info = env.step(action)

        # Render the environment
        env.render()

        # Control frame rate (optional, for smoother visualization)
        clock.tick(60)  # 60 FPS

        # Print progress occasionally
        if info.get("control_step", False):
            step_count += 1
            if step_count % 50 == 0:
                gap = env.state.workpiece_position - env.state.wire_position
                progress = (
                    env.state.workpiece_position / env.state.target_position
                ) * 100
                print(f"Progress: {progress:.1f}%, Gap: {gap:.1f}µm")

        if terminated:
            print(f"\nSimulation completed: {info}")
            # Keep window open for a moment
            pygame.time.wait(2000)
            break

    # Clean up
    env.close()
    pygame.quit()

    print("\n=== Visualization Example Complete ===")


if __name__ == "__main__":
    main()
