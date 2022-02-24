import json
import os
import re
import shlex
import subprocess
import tkinter as tk
from datetime import datetime
from io import BytesIO
from time import time
from tkinter import PhotoImage, ttk

import numpy as np
import pyperclip
import requests
from PIL import Image, ImageDraw, ImageFont, ImageTk, UnidentifiedImageError

SOLVER_PATH = './data/'
JS_PATH = './everything'
RESOURCES_PATH = './resources/'

board_map = {
    235: '1', 470: '2', 898: '3', 186: '4', 504: '5', 137: '6', 472: '7', 132: '8', # blue(hint)
    816: '1', 953: '2', 439: '3', 23: '4', 652: '5', 275: '6', 733: '7', 110: '8', # yellow(ticket)
    309: '0', 605: '1', 790: '2', 227: '3', 524: '4', 814: '5', 443: '6', 834: '7', 430: '8', # common
    732: 'M', 265: 'M', 831: 'M', 511: 'H', 817: 'H', 63: 'X', # wrong flag / mine / red mine / hint open / hint flag / start(NG)
    83: 'F', 245: 'C', # wrong flag / mine / red mine / hint open / hint flag / start(NG)
}

mine_number_range = np.s_[1 : 18, 1 : 11, : ]
mine_number_map = {83: '-', 701: '0', 821: '1', 690: '2', 25: '3', 808: '4', 295: '5', 420: '6', 307: '7', 419: '8', 294: '9'}
# face_map = {249: 'unpressed', 736: 'lose', 561: 'win',}
face_judge = 249

cell = 16
extra_height_data = 65
extra_width_data = 24
board_h_start = 54
board_w_start = 12

render_names = ('0', 'mine', 'dead', '1', '2', '3', '4', '-1')
render_imgs = {name: Image.open(RESOURCES_PATH + name + '.png') for name in render_names}

temp_img = None

class AutoScrollbar(ttk.Scrollbar):
    ''' A scrollbar that hides itself if it's not needed.
        Works only if you use the grid geometry manager '''
    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        ttk.Scrollbar.set(self, lo, hi)

    def pack(self, **kw):
        raise tk.TclError('Cannot use pack with this widget')

    def place(self, **kw):
        raise tk.TclError('Cannot use place with this widget')

class Zoom(ttk.Frame):
    ''' Simple zoom with mouse wheel '''
    def __init__(self, mainframe, path = './output.png'):
        ''' Initialize the main Frame '''
        ttk.Frame.__init__(self, master=mainframe,)
        # Vertical and horizontal scrollbars for canvas
        vbar = AutoScrollbar(self.master, orient='vertical')
        hbar = AutoScrollbar(self.master, orient='horizontal')
        vbar.grid(row=0, column=1, rowspan=5, sticky='ns')
        hbar.grid(row=5, column=0, sticky='we')
        # Open image
        self.image = Image.open(path)
        # Create canvas and put image on it
        self.canvas = tk.Canvas(self.master, highlightthickness=0,
                                xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.canvas.grid(row=0, column=0, rowspan=5, sticky='nswe')
        vbar.configure(command=self.canvas.yview)  # bind scrollbars to the canvas
        hbar.configure(command=self.canvas.xview)
        # Make the canvas expandable
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)
        # Bind events to the Canvas
        self.canvas.bind('<ButtonPress-1>', self.move_from)
        self.canvas.bind('<B1-Motion>',     self.move_to)
        self.canvas.bind('<MouseWheel>', self.wheel)  # with Windows and MacOS, but not Linux
        self.canvas.bind('<Button-5>',   self.wheel)  # only with Linux, wheel scroll down
        self.canvas.bind('<Button-4>',   self.wheel)  # only with Linux, wheel scroll up
        # Show image
        self.imscale = 1.0
        self.imageid = None
        self.delta = 0.75
        # Text is used to set proper coordinates to the image. You can make it invisible.
        self.text = self.canvas.create_text(0, 0, anchor='nw', text=' ')
        self.show_image()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def move_from(self, event):
        ''' Remember previous coordinates for scrolling with the mouse '''
        self.canvas.scan_mark(event.x, event.y)

    def move_to(self, event):
        ''' Drag (move) canvas to the new position '''
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def wheel(self, event):
        ''' Zoom with mouse wheel '''
        scale = 1.0
        # Respond to Linux (event.num) or Windows (event.delta) wheel event
        if event.num == 5 or event.delta == -120:
            scale        *= self.delta
            self.imscale *= self.delta
        if event.num == 4 or event.delta == 120:
            scale        /= self.delta
            self.imscale /= self.delta
        # Rescale all canvas objects
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self.canvas.scale('all', x, y, scale, scale)
        self.show_image()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def show_image(self, new = False):
        ''' Show image on the Canvas '''
        if self.imageid:
            self.canvas.delete(self.imageid)
            self.imageid = None
            self.canvas.imagetk = None  # delete previous image from the canvas
        width, height = self.image.size
        new_size = int(self.imscale * width), int(self.imscale * height)
        imagetk = ImageTk.PhotoImage(self.image.resize(new_size)) if not new else ImageTk.PhotoImage(self.image.resize(new_size))
        # Use self.text object to set proper coordinates
        self.imageid = self.canvas.create_image(self.canvas.coords(self.text),
                                                anchor='nw', image=imagetk)
        self.canvas.lower(self.imageid)  # set it into background
        self.canvas.imagetk = imagetk  # keep an extra reference to prevent garbage-collection

    def open(self, new_path):
        self.image = Image.open(new_path)
        self.imscale = 1 / self.imscale
        self.delta = 0.75
        self.show_image(new = True)

class Solver():
    def __init__(self, root):
        global temp_img
        root.title("WOM Solver")
        root.geometry('640x420')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        mainframe = ttk.Frame(root, padding="3 3 12 12")
        mainframe.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))

        self.frame = Zoom(mainframe)
        self.frame.grid(column=0, row=0, rowspan=5)


        ttk.Label(mainframe, text="Size (mines)", width=10).grid(column=2, row=0, sticky=tk.E)
        self.mines = tk.StringVar()
        ttk.Label(mainframe, textvariable=self.mines, width=10).grid(column=3, row=0, sticky=(tk.W, tk.E))

        self.temp = tk.Canvas(mainframe, highlightthickness=0, width=160, height=160)
        self.temp.grid(row=1, column=2, columnspan=2, sticky='nswe')
        temp_img = ImageTk.PhotoImage(Image.open('./info.png'))
        self.temp.create_image(0, 0, anchor='nw', image = temp_img)
        
        self.game_id = tk.StringVar()
        game_id_entry = ttk.Entry(mainframe, width=10, textvariable=self.game_id)
        game_id_entry.grid(column=2, columnspan=2, row=2, sticky=(tk.W, tk.E))
        game_id_entry.bind("<Return>", lambda *args: self.handle_solve())

        ttk.Button(mainframe, text="solve", command=self.handle_solve, width=5).grid(column=2, row=3, sticky=(tk.W, tk.E))
        ttk.Button(mainframe, text="paste", command=lambda: self.game_id.set(pyperclip.paste()), width=5).grid(column=3, row=3, sticky=(tk.W, tk.E))

        self.log = tk.Text(mainframe, state='disabled', width=22, height=10, wrap='none')
        self.log.grid(row=4, column=2, columnspan=2)

        # for child in mainframe.winfo_children(): 
        #     child.grid_configure(padx=2, pady=2)

        game_id_entry.focus()
        

    def save_open(self, img, path):
        img.save(path)
        self.frame.open(path)

    def writeToLog(self, msg):
        numlines = int(self.log.index('end - 1 line').split('.')[0])
        self.log['state'] = 'normal'
        if numlines == 10:
            self.log.delete(1.0, 2.0)
        if self.log.index('end-1c')!='1.0':
            self.log.insert('end', '\n')
        self.log.insert('end', msg)
        self.log['state'] = 'disabled'

    def writemsg(self, msg):
        if ':' in msg:
            m = msg.split(': ')
            self.writeToLog(str(datetime.now().strftime(r'[%H:%M:%S] ' + m[0])))
            self.writeToLog(('  ' + m[1]))
        else:
            self.writeToLog(str(datetime.now().strftime(r'[%H:%M:%S]')))
            self.writeToLog(('  ' + msg))

    def clearmsg(self):
        self.log['state'] = 'normal'
        self.log.delete(1.0, 11.0)
        self.log['state'] = 'disabled'

    def handle_solve(self):
        global temp_img

        self.temp.delete('image')
        self.clearmsg()

        game_id = self.game_id.get()
        if not game_id.isdecimal():
            self.writemsg('ERROR: Wrong game id')
            self.game_id.set('')
            return

        root.title('GAME ' + str(game_id))
        now = datetime.now()
        date_time = now.strftime(r'%m%d/%H%M%S')

        folder_path = SOLVER_PATH + '{:}/{:}'.format(date_time, game_id)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        self.writemsg('Fetching board...')

        try:
            img_src = 'https://minesweeper.online/screen/{:}-xp-16-{:}.png'.format(game_id, 14400000 - time() % 14400000 / 14400000)
            response = requests.get(img_src)
            with Image.open(BytesIO(response.content)) as img:

                self.save_open(img, folder_path + '/game.png')
                image_data = np.array(img)

                (height_data, width_data, temp) = image_data.shape
                height = (height_data - extra_height_data) // cell
                width = (width_data - extra_width_data) // cell
                assert width > 3 and height > 3

                board_img = Image.new("RGBA", (width * cell, height * cell), (255, 255, 255, 0))
                box = (board_w_start, board_h_start, board_w_start + width * cell, board_h_start + height * cell)
                board_img.paste(img.crop(box))

        except UnidentifiedImageError:
            self.writemsg('ERROR: Screenshot not found')
            return

        board_data = image_data[board_h_start : board_h_start + height * cell, board_w_start : board_w_start + width * cell, 0 : 1]
        mine_number_data = [image_data[16 : 37, 17 + 13 * i :28 + 13 * i, 0 : 1] for i in range(3)]
        face_data = image_data[14 : 40, width_data // 2 - 13 : width_data // 2 + 13, 0 : 1]

        def data_hash(data):
            return np.sum(data) % 997

        finished = False
        try:
            # primary judge
            if width >= 8 and data_hash(face_data) != face_judge:
                self.writemsg('WARNING: Game is already finished')
                finished = True
                # return

            board = '\n'.join(
                ''.join(
                    board_map[
                        data_hash(
                            board_data[h * cell : (h + 1) * cell, w * cell : (w + 1) * cell, : ]
                        )
                    ]
                for w in range(width)
                )
                for h in range(height)
            )

            mine_str = ''.join(mine_number_map[data_hash(s[mine_number_range])] for s in mine_number_data)
            mine_number = eval(mine_str) if '-' in mine_str else int(mine_str)

            if mine_number == -99:
                self.writemsg('ERROR: Too many flags')
                return
            elif mine_number == 0 and 'C' not in board:
                self.writemsg('WARNING: Game is already finished')
                finished = True

            temp_mine = mine_number
            mine_number += board.count('F')
            
            output = '{}x{}x{}\n{}'.format(width, height, mine_number, board)

            with open(folder_path + '/board.txt', 'w') as f:
                f.write(output)

            if 'H' in board:
                self.writemsg('ERROR: Hint found')
                return
            elif 'M' in board:
                self.writemsg('WARNING: Game is already finished')
                finished = True
            elif 'X' in board:
                self.writemsg('ERROR: Please click "x" to start')
                return

        except KeyError:
            self.writemsg('ERROR: Key error')
            return

        if finished:
            board.replace('M', 'C')
            output = '{}x{}x{}\n{}'.format(width, height, mine_number, board)
            with open(folder_path + '/board.txt', 'w') as f:
                f.write(output)
            
        def call_cmd(nf):
            cmd = 'node -e "require(\\"{}\\")(\\"{}\\"{})"'.format(JS_PATH, folder_path, nf)
            args = shlex.split(cmd)
            with subprocess.Popen(args, text=True, stdout=subprocess.PIPE) as proc:
                try:
                    a, b = proc.communicate(timeout=44)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    self.writemsg('ERROR: Time out')
                    return

        
        self.writemsg('Analysing...')

        misflag = False
        nf = ', true' if board.count('F') == 0 else ''
        call_cmd(nf)

        with open(folder_path + '/result.json') as f:
            result = json.load(f)

        if len(result) == 0: # misflag?
            misflag = True
            output = output.replace('F', 'C')
            with open(folder_path + '/board.txt', 'w') as f:
                f.write(output)
            call_cmd(', true')
            with open(folder_path + '/result.json') as f:
                result = json.load(f)
        elif sum(1 for hint in result if hint['prob'] > 0) == 0:
            call_cmd(', true')
            with open(folder_path + '/result.json') as f:
                result.extend(json.load(f))
            
        if len(result) == 0:
            self.writemsg('WARNING: Game is indeed finished')
            return

        if misflag:
            self.writemsg('WARNING: The board is invalid, switched to NF mode')

        self.writemsg('Rendering picture...')

        layer = board_img.copy()

        def draw(hint, style):
            x = hint['x'] * cell
            y = hint['y'] * cell
            layer.paste(render_imgs[style], (x, y))

        current_tier = 0
        current_weight = 8
        tier_weight = {0: (1, 0)}

        clears = []
        for hint in result:
            if hint['dead']:
                draw(hint, 'dead')
            elif hint['prob'] == 0:
                draw(hint, 'mine')
            elif hint['prob'] == 1:
                draw(hint, '0')
            else:
                if current_tier < 4 and hint['weight'] != current_weight:
                    current_tier += 1
                    current_weight = hint['weight']
                    tier_weight[current_tier] = (hint['prob'], hint['progress'])
                if current_tier == 1 and hint.get('commonClears', None) and not clears:
                    clears.extend(hint['commonClears'])
                draw(hint, str(current_tier))
        for hint in clears:
            draw(hint, '-1')

        board_img = Image.blend(board_img, layer, 0.5)

        info_img = Image.new("RGBA", (160, 120), (255, 255, 255, 1))
        font = ImageFont.truetype("Chalkduster.ttf", 16, encoding='utf-8')
        write = ImageDraw.Draw(info_img)
        sep = 24
        for i in range(1, min(len(tier_weight), 4)):
            info_img.paste(render_imgs[str(i)], (0, sep * i - cell))
            text = ' {:.2%}/{:.2%}'.format(*tier_weight[i]) if i == 1 else ' {:.2%}'.format(tier_weight[i][0])
            write.text((cell * 1.2, sep * i - cell + 1), text, 'black', font)
        
        temp_img = ImageTk.PhotoImage(info_img)
        self.temp.create_image(10, 0, anchor='nw', image = temp_img)

        self.mines.set(str('{}x{} ({})'.format(width, height, temp_mine)))

        self.save_open(board_img, folder_path + '/output.png')

        self.writemsg('Done!')

        return

root = tk.Tk()
Solver(root)
root.mainloop()
