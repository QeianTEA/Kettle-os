# main.py
import time
import sys
from modules.display import Display
from modules.input import Buttons
from modules import menu_screen

# import games
from games import snake
from games import volfied
from games import heatseekers
from games import datahop
from games import minesweeper
from games import chess

# import splash screen gif
from modules.img_loader import play_gif_from_index
import images.splash.splash_index


# Button mapping
BTN_PINS = {
    'UP': 6,
    'DOWN': 7,
    'LEFT': 8,
    'RIGHT': 9,
    'CONFIRM': 10,
    'SHOULDER_L': 11,
    'SHOULDER_R': 12
}

def splash(display):
    """
    Play splash GIF stored in /images/splash using images.splash.splash_index.IMAGES.
    Plays once and stays on last frame. If files missing or something fails, fallback to a text splash.
    """
    try:
        folder = "/images/splash"
        # Use the module you copied: images.splash.splash_index
        import images.splash.splash_index as splash_index_mod
        success = play_gif_from_index(display, splash_index_mod.IMAGES, folder,
                                      center=False, loops=1, hold_last=True)
        if success:
            return
        else:
            # playback failed (missing files etc.) -> fall through to text splash
            print("Splash playback returned failure; falling back to text")
    except Exception as e:
        print("Splash GIF failed (exception):", e)

    # fallback to text splash so user still sees something
    display.clear()
    title = "Kettle"
    tx = (display.width - (len(title) * 8)) // 2
    display.text(title, tx, 20)
    #display.text("v0.1", tx + 30, 34)
    display.show()
    time.sleep(1)




def short_display_error(display, msg):
    """Show short on-screen error (keeps it readable)."""
    display.clear()
    # trim to 16 chars per line roughly
    display.text("ERR", 0, 0)
    display.text(msg[:16], 0, 12)
    display.show()
    time.sleep(2)

def main():
    display = Display(sda_pin=4, scl_pin=5)
    buttons = Buttons(BTN_PINS)

    # -------------------------------
    # GAME REGISTRY
    # -------------------------------
    games = [
        {'name': "Snake", 'module': snake},
        {'name': "Volfied", 'module': volfied},
        {'name': "Heat Seekers", 'module': heatseekers},
        {'name': "Mike Sweeper", 'module': minesweeper},
        {'name': 'Chepp', 'module': chess}
        {'name': "Data Hop", 'module': datahop},
        {'name': "Mike", 'module': None}    # to be added later
    ]

    splash(display)

    sel = 0
    menu_screen.draw_menu(display, games, sel)

    while True:
        evt = buttons.get_event()

        if evt == 'LEFT' or evt == 'SHOULDER_L':
            sel = (sel - 1) % len(games)
            menu_screen.draw_menu(display, games, sel)

        elif evt == 'RIGHT' or evt == 'SHOULDER_R':
            sel = (sel + 1) % len(games)
            menu_screen.draw_menu(display, games, sel)

        elif evt == 'CONFIRM':
            game_module = games[sel]['module']
            if game_module is None:
                # no game implemented yet
                display.clear()
                display.text("Not ready!", 20, 25)
                display.show()
                time.sleep(1.2)
            else:
                # Safety: verify the module exposes a callable run()
                run_func = getattr(game_module, 'run', None)
                if not callable(run_func):
                    # print helpful debug to REPL and show short message
                    print("Selected game module has no callable run(display, buttons):", game_module)
                    # if the module is a package, show its attributes to help debug
                    try:
                        attrs = dir(game_module)
                        print("module attrs:", attrs)
                    except Exception:
                        pass
                    short_display_error(display, "Game module bad")
                else:
                    # try running the game and print full traceback on error
                    try:
                        run_func(display, buttons)
                    except Exception as e:
                        # Print full traceback to REPL (Thonny console) for debugging
                        sys.print_exception(e)
                        # Also show a short message on screen so user knows something failed
                        short_display_error(display, repr(e))
            # back to menu
            menu_screen.draw_menu(display, games, sel)

        time.sleep_ms(30)

if __name__ == "__main__":
    main()
