#!/usr/bin/env python

import asyncio
import json
import logging
import websockets
import gphoto2 as gp

import sys
import os
from os import listdir
from os.path import isfile, join

logging.basicConfig()

USERS = set()

image_dir = "/home/pi/pictures"
if len(sys.argv) > 1:
    image_dir = sys.argv[1]

# Returns a list of Numbers (extension=False) or a list of Strings (extension=True)
def get_images(path, extension=False):
    filenames_stripped = [f.split('.')[0] for f in listdir(path) if isfile(join(path, f))]
    filenames_numbers = []

    for filename in filenames_stripped:
        try: 
            filenames_numbers.append(int(filename))
        except ValueError:
            pass
    
    return ["{:0>4d}.jpg".format(filename) if extension else filename for filename in filenames_numbers]

def get_next_filename(path):
    filenames_numbers = get_images(path)

    if filenames_numbers:
        return "{:0>4d}.jpg".format(max([int(n) for n in filenames_numbers]) + 1)
    else:
        return "0000.jpg"

async def send_message(message):
    if USERS:
        message_json = json.dumps(message)
        await asyncio.wait([user.send(message_json) for user in USERS])

async def register(websocket):
    USERS.add(websocket)
    print("Connected! {}".format(websocket))

async def unregister(websocket):
    USERS.remove(websocket)

async def capture(websocket):
    # Capture Image
    try:
        camera = gp.check_result(gp.gp_camera_new())
        gp.check_result(gp.gp_camera_init(camera))

        print('Capturing Image...')
        file_path = gp.check_result(gp.gp_camera_capture(camera, gp.GP_CAPTURE_IMAGE))
        print('Camera file path: {0}/{1}'.format(file_path.folder, file_path.name))
        filename = get_next_filename(image_dir)
        target = os.path.join(image_dir, filename)

        print('Copying image to', target)
        camera_file = gp.check_result(gp.gp_camera_file_get(camera, file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL))
        gp.check_result(gp.gp_file_save(camera_file, target))
        gp.check_result(gp.gp_camera_exit(camera))

        print('Image Ready!')
        await send_message({
            'event': 'imageReady',
            'filename': filename
        })
    except Exception as e:
        print("Error while trying to take photo: " + str(e))
        await send_message({
            'event': 'captureError',
            'error': str(e)
        })

async def list_images(websocket):
    # List all images in the folder
    await send_message({
        'event': 'allImages',
        'images': get_images(image_dir, extension=True)
    })

async def handler(websocket, path):
    await register(websocket)
    try:
        async for message in websocket:
            print(message)
            data = json.loads(message)
            
            if data['action'] == 'capture':
                await capture(websocket)
            elif data['action'] == 'list':
                await list_images(websocket)
            elif data:
                logging.error("unsupported event: {}".format(data))
    finally:
        await unregister(websocket)

asyncio.get_event_loop().run_until_complete(websockets.serve(handler, '0.0.0.0', 6789))
asyncio.get_event_loop().run_forever()

gp.check_result(gp.use_python_logging())