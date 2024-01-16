from hashlib import sha1
import urllib.parse

import bcoding
import random
import socket
import asyncio
import struct

class Tracker:
    def __init__(self, torrent):
        self.torrent = torrent
        self.p_id = get_peer_id()
    async def connect(self,
                      start: bool = True,
                      uploaded: int = 0,
                      downloaded: int = 0):
        
        info = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.p_id,
            'port': 6969,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': self.torrent.total_size - downloaded,
            'compact': 1}
        if start:
            info['event'] = 'started'
        
        url_arr = self.torrent.url.split(":")
        new_url = url_arr[1][2::]
        port_arr = url_arr[2].split("/")
        target_port = int(port_arr[0])
        info['port'] = int(target_port)

        reader, writer = await asyncio.open_connection(new_url, int(target_port))
        left = info['left']
        event = info['event']
        port = info['port']
        url = f'/announce?info_hash={urllib.parse.quote(self.torrent.info_hash)}&peer_id={urllib.parse.quote(self.p_id)}&port={port}&uploaded={uploaded}&downloaded={downloaded}&left={left}&event={event}'

        request = f"GET {url} HTTP/1.1\r\nHost: {self.torrent.url}\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        response = await reader.read(4096)
        response = response.decode()
        # response_arr = response.split('\n')
        # response_data = response_arr[-1]
        index = response.find('d8:')
        response_data = response[index:]
        data_dict = bcoding.bdecode(response_data)
        # s.close()

        print(data_dict)

        writer.close()
        await writer.wait_closed()
        return data_dict




def get_peer_id():
    peer_id = '-MB0001-' + ''.join([str(random.randint(0, 9)) for _ in range(12)])
    peer_id = peer_id.encode()
    hash = sha1(peer_id).digest()
    return hash


class Torrent:
    def __init__(self, fn, upload=False):
        self.fn = fn

        with open(self.fn, 'rb') as file:
            meta_info = file.read()
            self.meta_info = bcoding.bdecode(meta_info)
            info = bcoding.bencode(self.meta_info['info'])
            self.info_hash = sha1(info).digest()
            self.url = self.meta_info['announce']
            self.total_size = self.meta_info['info']['length']
            if upload:
                self.file_name = self.meta_info['info']['name']
            else:
                self.file_name = 'torrent' + self.meta_info['info']['name']

            pieces_data = self.meta_info['info']['pieces']
            #print(pieces_data)
            hashes = []
            off = 0

            while off < len(pieces_data):
                hashes.append(pieces_data[off:off + 20])
                off += 20
            self.pieces = hashes

