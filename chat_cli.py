"""Chat with the bot in the terminal, pretending to be a WhatsApp customer.

    python chat_cli.py                       # default fake number
    python chat_cli.py --phone 919812345678  # another "customer" (own saved requirements)
    python chat_cli.py --debug               # also show tool calls

Commands inside the chat:  /profile  show saved requirements  |  /reset  forget this customer  |  /quit
"""
import argparse
import logging
import os
import sys

from sqlalchemy import func, select

from app.db import Car, Customer, get_session, init_db
from app.llm import OPENAI_MODEL, handle_message


def show_profile(phone: str) -> None:
    with get_session() as s:
        customer = s.scalar(select(Customer).where(Customer.phone == phone))
        if customer is None:
            print("  (no customer record yet)")
            return
        print("  saved requirements:", customer.profile or "none")
        print("  handoff requested: ", customer.handoff_requested, customer.handoff_note or "")


def reset_customer(phone: str) -> None:
    with get_session() as s:
        customer = s.scalar(select(Customer).where(Customer.phone == phone))
        if customer is not None:
            s.delete(customer)  # messages are deleted with it
    print("  customer forgotten, starting fresh")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone", default="919999900001", help="fake customer phone number")
    parser.add_argument("--debug", action="store_true", help="show tool calls and info logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Add it to your .env file (see .env.example).")
    try:
        init_db()
    except RuntimeError as exc:
        sys.exit(str(exc))
    with get_session() as s:
        if not s.scalar(select(func.count(Car.id))):
            sys.exit("No cars in the database. Run: python -m scripts.seed --reset")

    print(f"Chatting as {args.phone} with model {OPENAI_MODEL}. Type /quit to exit.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/profile":
            show_profile(args.phone)
            continue
        if text == "/reset":
            reset_customer(args.phone)
            continue

        reply = handle_message(args.phone, text)
        if reply is None:
            continue
        if args.debug:
            for line in reply.trace:
                print(f"  [tool] {line}")
        print(f"Bot: {reply.text}")
        if reply.handoff_requested:
            print("  [salesperson notified]")
        print()


if __name__ == "__main__":
    main()