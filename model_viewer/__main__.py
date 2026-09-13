def main():
    import argparse
    parser = argparse.ArgumentParser(description='Divinity II source model viewer')
    parser.add_argument('--audit-package')
    parser.add_argument('--audit-output')
    args = parser.parse_args()
    if bool(args.audit_package) != bool(args.audit_output):
        parser.error('both audit arguments are required together')
    if args.audit_package:
        from .diagnostics import run
        run(args.audit_package,args.audit_output)
    else:
        from .desktop import main as desktop_main
        desktop_main()


if __name__ == '__main__':
    main()
