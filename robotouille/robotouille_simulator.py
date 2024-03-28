import pygame
from utils.robotouille_input import create_action_from_control
from robotouille.robotouille_env import create_robotouille_env
import asyncio
import json
import pickle
import base64
import websockets
import time


def simulator(environment_name: str, seed: int=42, role="client", host="ws://localhost:8765", noisy_randomization: bool=False):
    if role == "server":
        server_loop(environment_name, seed, noisy_randomization)
    else:
        client_loop(environment_name, seed, host, noisy_randomization)

def server_loop(environment_name: str, seed: int=42, noisy_randomization: bool=False):
    print("I am server")
    async def simulator(websocket):
        print("Hello client", websocket)
        env, json_data, renderer = create_robotouille_env(environment_name, seed, noisy_randomization)
        obs, info = env.reset()
        renderer.render(obs, mode='human')
        done = False
        interactive = False  # Adjust based on client commands later if needed
        try:
            while not done:
                action_message = await websocket.recv()
                encoded_action, encoded_args = json.loads(action_message)
                action = pickle.loads(base64.b64decode(encoded_action))
                args = pickle.loads(base64.b64decode(encoded_args))
                #print((action, args))
                time.sleep(0.25)

                reply = None

                try:
                    obs, reward, done, info = env.step(action=action, args=args, interactive=interactive)
                    reply = json.dumps({"valid": True, "done": done})
                    renderer.render(obs, mode='human')
                except AssertionError:
                    env_data = pickle.dumps(env.get_state())
                    encoded_env_data = base64.b64encode(env_data).decode('utf-8')
                    obs_data = pickle.dumps(obs)
                    encoded_obs_data = base64.b64encode(obs_data).decode('utf-8')
                    reply = json.dumps({"valid": False, "env": encoded_env_data, "obs": encoded_obs_data, "done": False})
                
                time.sleep(0.25)
                await websocket.send(reply)
        except BaseException as e:
            print(e)
        finally:
            renderer.render(obs, close=True)
            print("GG")

    start_server = websockets.serve(simulator, "localhost", 8765)

    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_forever()

def client_loop(environment_name: str, seed: int = 42, host="ws://localhost:8765", noisy_randomization: bool = False):
    uri = host

    async def send_actions(websocket, shared_state):
        env = shared_state["env"]
        renderer = shared_state["renderer"]
        renderer.render(shared_state["obs"], mode='human')
        online = True
        while not shared_state["done"]:
            pygame_events = pygame.event.get()
            mousedown_events = list(filter(lambda e: e.type == pygame.MOUSEBUTTONDOWN, pygame_events))
            keydown_events = list(filter(lambda e: e.type == pygame.KEYDOWN, pygame_events))
            action, args = create_action_from_control(env, shared_state["obs"], mousedown_events + keydown_events, renderer)

            online = not (pygame.key.get_mods() & pygame.KMOD_CAPS)

            if action is not None:
                if online:
                    encoded_action = base64.b64encode(pickle.dumps(action)).decode('utf-8')
                    encoded_args = base64.b64encode(pickle.dumps(args)).decode('utf-8')
                    await websocket.send(json.dumps((encoded_action, encoded_args)))
                shared_state["obs"], reward, done, info = env.step(action=action, args=args, interactive=True)
            renderer.render(env.get_state(), mode='human')

            await asyncio.sleep(0)  # Yield control to allow other tasks to run

    async def receive_responses(websocket, shared_state):
        while not shared_state["done"]:
            response = await websocket.recv()
            data = json.loads(response)
            shared_state["done"] = data["done"]

            if(not data["valid"]):
                shared_state["env"].set_state(pickle.loads(base64.b64decode(data["env"])))
                shared_state["obs"] = pickle.loads(base64.b64decode(data["obs"]))

    async def interact_with_server():
        async with websockets.connect(uri) as websocket:
            env, _, renderer = create_robotouille_env(environment_name, seed, noisy_randomization)
            obs, info = env.reset()
            shared_state = {"done": False, "env": env, "renderer": renderer, "obs": obs}
            sender = asyncio.create_task(send_actions(websocket, shared_state))
            receiver = asyncio.create_task(receive_responses(websocket, shared_state))
            await asyncio.gather(sender, receiver)
            # Additional cleanup if necessary

    asyncio.get_event_loop().run_until_complete(interact_with_server())