#!/usr/bin/python3.7

import os, time, glob, subprocess, json
import psutil
import RPi.GPIO as GPIO
import tkinter as tk

## Google OAuth and Drive setup ##
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials
GoogleAuth.DEFAULT_SETTINGS['client_config_file'] = '/auth'

## SETUP GPIO ##
GPIO.setmode(GPIO.BCM)

GRN_BTN_PIN = 5
RED_BTN_PIN = 4
GRN_LED_PIN = 12
RED_LED_PIN = 18

for led_pin in [RED_LED_PIN, GRN_LED_PIN]:
    GPIO.setup(led_pin, GPIO.OUT)
    GPIO.output(led_pin, GPIO.LOW)

for btn_pin in [RED_BTN_PIN, GRN_BTN_PIN]:
    GPIO.setup(btn_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(btn_pin, GPIO.FALLING, bouncetime=750)

## SETUP PATHS ##
hooks_path = '/home/pi/storybooth/hooks/'
rec_path = '/home/pi/storybooth/rec/'
if not os.path.isdir(hooks_path):
    subprocess.call('/home/pi/make_dirs.sh', shell=True)

## adjustment variables (in seconds) ##
SETTINGS = {
    'idle_time': 30,            # max time camera is on without recording before idling off
    'time_limit': 120,          # max record time
    'time_limit_warning': 15,   # seconds before time limit to start warning
    'blink_length': 0.5         # time interval between red LED blinks during time limit warning
    }

## other global variables ##
_G = {
    'is_ready': False,
    'is_blinking': False,
    'is_recording': False,
    'record_time': 0
    }

### DEFINE FUNCTIONS ###

def wake_display():
    CONTROL = 'vcgencmd'
    CONTROL_UNBLANK = [CONTROL, 'display_power', '1']
    subprocess.call(CONTROL_UNBLANK)

def is_picam_running():
    for proc in psutil.process_iter():
        if proc.name() == 'picam':
            return True
    return False

def start_picam():
    subprocess.Popen('/home/pi/picam/picam --alsadev hw:1,0 --rotation 180 -p', shell=True)
    GPIO.output(GRN_LED_PIN, GPIO.HIGH)
    time.sleep(1)
    _G['is_ready'] = True
    
def kill_picam():
    for proc in psutil.process_iter():
        if proc.name() == 'picam':
            proc.kill()
    GPIO.output(GRN_LED_PIN, GPIO.LOW)
    _G['is_ready'] = False

def start_record():
    print('Start record...')
    GPIO.output(RED_LED_PIN, GPIO.HIGH)
    _G['is_recording'] = True
    with open(os.path.join(hooks_path, 'start_record'), 'w') as fp:
        pass

def stop_record():
    print('Stop record...')
    GPIO.output(RED_LED_PIN, GPIO.LOW)
    _G['is_blinking'] = False
    _G['is_recording'] = False
    _G['record_time'] = 0
    
    with open(os.path.join(hooks_path, 'stop_record'), 'w') as fp:
        pass
    print('Processing...')
    time.sleep(2)
    kill_picam()
    finalize(get_latest_file())
    
def get_latest_file():
    list_of_files = glob.glob(rec_path + '*.ts')
    latest_file = max(list_of_files, key=os.path.getctime)
    filename_w_ext = os.path.basename(latest_file)
    filename, file_extension = os.path.splitext(filename_w_ext)
    return filename
    
def convert(filename):
    os.system('ffmpeg -hide_banner -i {path}{filename}.ts -c:v copy -c:a copy -bsf:a aac_adtstoasc {path}{filename}.mp4'.format(path=rec_path, filename=filename))

def auth(filename):
    gauth = GoogleAuth()
    drive = GoogleDrive(gauth)
    scope = 'https://www.googleapis.com/auth/drive.file'
        
    gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name('auth/credentials.json', scope)

    with open('auth/folder.json') as f:
        data = json.load(f)

    location = data['location']     # get device location

    file = filename+'.mp4'
    filesize = os.path.getsize(rec_path + file)
    print('Uploading {file} ({size} MB) to Google Drive folder: {folderName}...'.format(file=file, size=round(filesize/2**20, 3), folderName=location))
    
    gfile = drive.CreateFile({
        'title': filename+'.mp4',
        'parents': [{
            'kind': 'drive#fileLink',
            'teamDriveId': data['team_drive_id'],
            'id': data['folder_ids'][location],   # set upload folder id based on location
        }]
    })
    gfile.SetContentFile(rec_path + file)
    gfile.Upload(param={'supportsTeamDrives': True})
    if gfile.uploaded:
        print('Upload complete!\n================\nReady...')
        return 'success'
    else:
        print('There may have been an error in the uploading process.')
        return 'err'
    
def finalize(filename):
    
    ## Display window ##
    win = tk.Tk()
    print('tk OK')
    win.title('Uploading story')
    
    win_width = 255
    win_height = 128
    
    screen_width = 800
    screen_height = 480
    
    center_x = int(screen_width/2 - win_width/2)
    center_y = int(screen_height/2 - win_height/2)
    
    win.geometry(f'{win_width}x{win_height}+{center_x}+{center_y}')
    
    abccm_blue = '#003e73'
    
    v = tk.StringVar()
    v.set('Uploading video...')        
    win.configure(bg = abccm_blue)
    tk.Label(win, textvariable=v, fg='#fff', bg=abccm_blue, font=('Arial', 18)).pack(pady=20)
    win.update()
    
    ## Process and upload video ##
    convert(filename)
    
    if (auth(filename) == 'success'):
        v.set('Upload complete.\n\nThank you for sharing!')
    else:
        v.set('There may have been\na problem with the upload.')
    win.update()
    win.after(3500, lambda:win.destroy())
    win.mainloop()

### START PROGRAM ###

if __name__ == '__main__':

    if is_picam_running:
        kill_picam()
    
    print('Press READY button to start camera.')
    button_last_pressed_time = time.time()

    ## MAIN LOOP ##
    while True:

        try:
            if GPIO.event_detected(GRN_BTN_PIN):
                print('Press RECORD button to start or stop recording')
                button_last_pressed_time = time.time()
                if is_picam_running():
                    kill_picam()
                else:
                    wake_display()
                    time.sleep(1)
                    start_picam()
            
            if _G['is_ready'] and GPIO.event_detected(RED_BTN_PIN):
                button_last_pressed_time = time.time()
                if not _G['is_recording']:
                    start_record()
                    start_record_time = time.time()
                else:
                    stop_record()
            
            if _G['is_recording']:
                _G['record_time'] = time.time() - start_record_time

                ## START BLINKING WITH X SECONDS LEFT ##
                if _G['record_time'] > SETTINGS['time_limit'] - SETTINGS['time_limit_warning'] and not _G['is_blinking']:
                    _G['is_blinking'] = True
                    blink_tick_start = time.time()
                
                if _G['is_blinking']:
                    if time.time() - blink_tick_start > SETTINGS['blink_length']:
                        if GPIO.input(RED_LED_PIN):
                            GPIO.output(RED_LED_PIN, GPIO.LOW)
                        else:
                            GPIO.output(RED_LED_PIN, GPIO.HIGH)
                        blink_tick_start = time.time()

                ## STOP RECORDING AT TIME LIMIT ##
                if _G['record_time'] > SETTINGS['time_limit']:
                    print('Recording time limit reached.')
                    stop_record()

            elif is_picam_running() and time.time() - button_last_pressed_time > SETTINGS['idle_time']:
                print('picam idling off...')
                kill_picam()
            
            time.sleep(0.1)     # limit loop rate to ease CPU usage
                
        except KeyboardInterrupt:
            print('\nExiting...')
            GPIO.cleanup()
            break