# modules/menu_screen.py
def draw_menu(display, games, selected_index):
    display.clear()

    title = "Kettle"
    tx = (display.width - len(title) * 8) // 2
    display.text(title, tx, 0)

    game = games[selected_index]
    name = game['name']

    nx = (display.width - len(name) * 8) // 2
    display.text(name, nx, 12)

    display.rect(44, 26, 40, 30)

    display.text("<", 4, 36)
    display.text(">", display.width - 10, 36)

    display.show()
