pip install rawpy numpy pillow tkinterdnd2 pyinstaller
pyinstaller --onefile --windowed --name BayerChannels --collect-all tkinterdnd2 --collect-all rawpy bayer_gui.py
