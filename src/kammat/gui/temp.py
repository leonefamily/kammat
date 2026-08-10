# -*- coding: utf-8 -*-
"""
Created on Mon Feb  6 18:03:44 2023

@author: dgrishchuk
"""

import math
import PySimpleGUI as sg

layout = [
    [sg.Graph(
        canvas_size=(800, 600),
        graph_bottom_left=(-105,-105),
        graph_top_right=(105,105),
        background_color='black',
        key='graph')],
    [sg.Push(), sg.Button('Save')],
]

sg.set_options(dpi_awareness=True)

window = sg.Window('Graph of Sine Function', layout, grab_anywhere=True, finalize=True)
graph = window['graph']

# Draw axis
graph.DrawLine((-100,0), (100,0), color='white')
graph.DrawLine((0,-100), (0,100), color='white')

for x in range(-100, 101, 20):
    graph.DrawLine((x,-3), (x,3), color='white')
    if x != 0:
        graph.DrawText( x, (x,-10), color='cyan')

for y in range(-100, 101, 20):
    graph.DrawLine((-3,y), (3,y), color='white')
    if y != 0:
        graph.DrawText( y, (-10,y), color='cyan')

# Draw Graph
for xx in range(-2000,2000):
    x = xx / 20
    y1 = math.sin(x/20)*70
    y2 = math.cos(x/20)*70
    graph.DrawPoint((x,y1), size=1, color='green')
    graph.DrawPoint((x,y2), size=1, color='red')

while True:

    event, values = window.read()

    if event == sg.WIN_CLOSED:
        break
    elif event == 'Save':
        filename='test.jpg'
        window['graph'].save_element_screenshot_to_disk(filename)

window.close()