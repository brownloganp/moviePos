import argparse
from pathlib import Path

from .store import Store
from .ticket_print import DEFAULT_PRINTER

DEFAULT_DB = Path(__file__).resolve().parent.parent / "moviepos.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="Movie theater point of sale")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database file (default: ./moviepos.db)")
    parser.add_argument("--fullscreen", action="store_true", help="run fullscreen (Esc exits)")
    parser.add_argument("--no-web", action="store_true", help="don't start the phone check-in web app")
    parser.add_argument("--web-port", type=int, default=8080, help="port for the phone web app (default: 8080)")
    parser.add_argument("--web-host", help="address phones should use, if auto-detection picks the wrong one")
    parser.add_argument("--no-customer-display", action="store_true", help="don't open the customer-facing window")
    parser.add_argument("--customer-fullscreen", action="store_true", help="show the customer window full screen")
    parser.add_argument("--printer", default=DEFAULT_PRINTER, help=f"receipt printer queue name (default: {DEFAULT_PRINTER})")
    parser.add_argument("--no-print", action="store_true", help="don't print tickets automatically")
    parser.add_argument("--printer-dots", type=int, default=576, help="printable width in dots (80mm printers: 576)")
    parser.add_argument("--printer-no-cut", action="store_true", help="don't send the paper-cut command")
    parser.add_argument("--no-demo", action="store_true", help="don't add sample data to a new, empty database")
    args = parser.parse_args()

    store = Store(args.db)
    if store.is_empty() and not args.no_demo:
        store.seed_demo()

    from .app import App
    from .web import start_phone_access

    phone = None if args.no_web else start_phone_access(store, args.db, args.web_port, args.web_host)
    if phone and not phone.running:
        print(phone.error, flush=True)
    try:
        App(
            store, fullscreen=args.fullscreen, phone=phone,
            customer_display=not args.no_customer_display, customer_fullscreen=args.customer_fullscreen,
            printer_name=None if args.no_print else args.printer, printer_dots=args.printer_dots,
            printer_cut=not args.printer_no_cut,
        ).mainloop()
    finally:
        if phone:
            phone.stop()
        store.close()


if __name__ == "__main__":
    main()
