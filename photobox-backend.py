#!/usr/bin/env python

import asyncio
import json
import logging
import websockets
import gphoto2 as gp
import subprocess
from escpos import *

import sys
import os
from os import listdir
from os.path import isfile, join

try:
    import RPi.GPIO as GPIO
    can_use_gpio = True
except ModuleNotFoundError as e:
    can_use_gpio = False

logging.basicConfig()

USERS = set()
messages = []

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
            'filename': filename,
            'name': filename.split('.')[0]
        })
        
    except Exception as e:
        print("Error while trying to take photo: " + str(e))
        await send_message({
            'event': 'captureError',
            'error': str(e)
        })

async def print_image(websocket, base64_image):
    try:
        with open("/home/pi/temp.b64", "w") as text_file:
            text_file.write(base64_image)

        p = printer.Usb(0x0fe6, 0x811e, 98, 0x02, 0x02)
        p.text(" ")

        job_id = subprocess.call(['convert inline:/home/pi/temp.b64 -rotate "90"  -density 203 -brightness-contrast 50x-10 -remap pattern:gray50 -dither FloydSteinberg ps:/dev/stdout | lp -s'], shell=True)

        await send_message({
            'event': 'printEnqueued',
            'jobId': str(job_id)
        })
        
    except Exception as e:
        print("Error while trying to print photo: " + str(e))
        await send_message({
            'event': 'printError',
            'jobId': str(e)
        })        

async def list_images(websocket):
    # List all images in the folder
    await send_message({
        'event': 'allImages',
        'images': get_images(image_dir, extension=True)
    })

async def poll_button():
    while True:
        if messages:
            message = messages.pop()
            await send_message({
                'event': message
            })

        await asyncio.sleep(.1)

def button_callback(channel):
    global messages
    messages.append('buttonPressed')

def settings_callback(channel):
    global messages
    messages.append('settings')

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
            elif data['action'] == 'print' and data['image']:
                await print_image(websocket, data['image'])
            elif data:
                logging.error("unsupported event: {}".format(data))
    finally:
        await unregister(websocket)

if can_use_gpio:
    GPIO.setmode(GPIO.BOARD)

    # Photo button Setup
    take_photo_pin = 8
    GPIO.setup(take_photo_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(take_photo_pin, GPIO.FALLING, callback=button_callback, bouncetime=500)

    # Shutdown button Setup
    shutdown_pin = 11
    GPIO.setup(shutdown_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    def shutdown_callback(channel):
        subprocess.call(['sudo poweroff'], shell=True)

    GPIO.add_event_detect(shutdown_pin, GPIO.FALLING, callback=shutdown_callback, bouncetime=1000)

    # Reload button Setup
    reload_pin = 13
    GPIO.setup(reload_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    def reload_callback(channel):
        os.execl('/home/pi/startup.sh', '')

    GPIO.add_event_detect(reload_pin, GPIO.FALLING, callback=reload_callback, bouncetime=1000)
    
    # Settings button Setup
    settings_pin = 15
    GPIO.setup(settings_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(settings_pin, GPIO.FALLING, callback=settings_callback, bouncetime=1000)

loop = asyncio.get_event_loop()
loop.run_until_complete(websockets.serve(handler, '0.0.0.0', 6789))

gpio_task = loop.create_task(poll_button())
loop.run_until_complete(gpio_task)

loop.run_forever()

gp.check_result(gp.use_python_logging())