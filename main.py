import json
import argparse
from worker import post_next_approved, generate_preview, post_to_facebook

def main():
    p = argparse.ArgumentParser(description="ADG | AI Facebook Poster (DB-backed)")
    p.add_argument("cmd", choices=["post-next-approved", "generate-preview", "post"])
    p.add_argument("--id", type=int, default=0, help="Post ID for generate-preview/post")
    args = p.parse_args()

    if args.cmd == "post-next-approved":
        result = post_next_approved()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.id <= 0:
        raise SystemExit("--id is required for this command")

    if args.cmd == "generate-preview":
        result = generate_preview(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "post":
        result = post_to_facebook(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
