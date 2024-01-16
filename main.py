import argparse
import asyncio

import tracker
import client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('torrent',
                        help='the .torrent to download/upload')
    parser.add_argument('-d', '--download',
                        help='whether or not downloading')
    parser.add_argument('-a', '--address',
                        help='address and port for direct download, <address:port>')

    args = parser.parse_args()

    #print(args.torrent)
    print("\n About to Start \n")

    if args.download == 'no': #upload
        torr = tracker.Torrent(args.torrent, True)
        server = client.Client(torr, True)
        asyncio.run(server.upload())

    else: #download
        c = client.Client(tracker.Torrent(args.torrent))
        if args.address:
            addr = args.address.split(':')
            peer = {}
            ip = addr[0]
            port = addr[1]
            asyncio.run(c.start_direct(ip, port))
        else:
            asyncio.run(c.start_client())

if __name__ == '__main__':
    main()