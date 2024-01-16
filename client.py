import tracker
import asyncio
import peer as peerClass
import time
import socket
import struct
import math
import os
import random 
from collections import defaultdict

from hashlib import sha1

# MAX_PEERS = 10 old static amount of peers
# new version dynamically spawns workers
BLOCK_SIZE = 16384

class Client:
    def __init__(self, torrent, upload=False):
        self.tracker = tracker.Tracker(torrent)
        self.manager = PieceManager(torrent, upload)
        self.peers = []
        self.stopped = False
        self.complete = False

    # old run client
    async def run_client(self):
        self.peers = [peerClass.Peer(self.peer_queue, self.tracker.p_id, self.manager, self.tracker.torrent.info_hash) for _ in range(MAX_PEERS)]
        prev_ts = None
        interval = 6000
        while True:
            if self.complete:
                break
            if self.stopped:
                print("aborted")
                break

            curr_ts = time.time()
            if prev_ts is None or curr_ts - prev_ts >= interval:
                if prev_ts is None:
                    resp = await self.tracker.connect()
                else:
                    resp = await self.tracker.connect(False)
                
                if resp:
                    prev_ts = curr_ts
                    interval = resp['interval']
                    while not self.peer_queue.empty():
                        self.peer_queue.get_nowait()

                    peers = resp['peers']
                    if type(peers) is list:
                        peers = [(peer['ip'], peer['port']) for peer in peers]
                    else:
                        num_peers = len(peers)/6
                        peers = [peers[i:i+6] for i in range(num_peers)]
                        peers = [(socket.inet_ntoa(peer[:4]), struct.unpack('>H', peer[4:])[0]) for peer in peers]
            
                    for peer in peers:
                        self.peer_queue.put_nowait(peer)
            else:
                await asyncio.sleep(5) # let other things do work
        
        for peer in self.peers:
            peer.close()
        self.stopped = True
        self.manager.close()

    async def start_client(self):
        resp = await self.tracker.connect()
        #print(f"\n resp: {resp} \n")
        resp_list = resp['peers']
        peers = []
        if type(resp_list) != list: # compact peer list support
            for i in range(0, len(resp_list), 6):
                bytes = resp_list[i:i+6] # get each 6 byte combo of ip and port
                temp_peer = {}
                temp_peer['ip'] = socket.inet_ntoa(bytes[:4]) # get ip
                temp_peer['port'] = struct.unpack('>H', bytes[4:])[0]
                peers.append(temp_peer)
        else:
            peers = resp_list
        peer_list = [peerClass.Peer(self.tracker.p_id, self.manager, self.tracker.torrent.info_hash, peer['ip'], peer['port']) for peer in peers]
        tasks = []
        #print(f"\n peer_list: {peer_list} \n")
        for peer in peer_list:
            
            tasks.append(asyncio.create_task(run(peer))) 
        await asyncio.gather(*tasks, return_exceptions=False)
        print("FINISHED DOWNLOADING \n")

    async def start_direct(self, ip, port):
        peer = peerClass.Peer(self.tracker.p_id, self.manager, self.tracker.torrent.info_hash, ip, port)
        tasks = []
        tasks.append(asyncio.create_task(run(peer))) 
        await asyncio.gather(*tasks, return_exceptions=False)
        print("FINISHED DOWNLOADING \n")

    async def upload(self):
        server = await asyncio.start_server(lambda r, w: upload_handler(r, w, self.manager), '127.0.0.1', 6969)
        print('Server Started')
        async with server:
            await server.serve_forever()

async def upload_handler(reader, writer, piece_manager):
    try:
        msg = await reader.readexactly(68)
        if len(msg) < 68:
            raise Exception("failed to read handshake")
        unpacked = struct.unpack('>B19s8s20s20s', msg)

        # send back handshake
        our_id = '-MB0001-' + ''.join([str(random.randint(0, 9)) for _ in range(12)])
        our_id = our_id.encode()
        response = struct.pack(
            '>B19s8x20s20s',
            19,
            b'BitTorrent protocol',
            piece_manager.torrent.info_hash,
            our_id)
        
        writer.write(response)
        await writer.drain()

        # num_pieces = len(piece_manager.torrent.pieces)
        # bitlen = num_pieces
        # if bitlen % 8 != 0:
        #     bitlen += (8 - bitlen % 8)
        # bs = bitstring.BitArray(length=bitlen)
        # for i in range(num_pieces):
        #     bs[i] = 1

        # send bitfield, find a better library to get bitfield
        # currently only send pg2600.txt bitfield
        bitfield = b'\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe'
        message = struct.pack(f'>Ib{len(bitfield)}s', 1 + len(bitfield), 5, bitfield)
        writer.write(message)
        await writer.drain()

        msg_len = 0
        while True:
            resp = await reader.read(4)
            if len(resp) >= 4:
                msg_len = struct.unpack('>I', resp[0:4])[0]
            if msg_len > 0:
                break

        resp = await reader.readexactly(msg_len)
        if resp[0] == 2:
            message = struct.pack('>Ib', 1, 1)
            writer.write(message)
            await writer.drain()

        peer = peerClass.Peer(our_id, piece_manager, piece_manager.torrent.info_hash, 'localhost', '6969')
        peer.set_as_upload(reader, writer)

        while True:
            await peer.handle_msg()
        
        
    except Exception as e:
        print(e)

        
            
async def run(peer):
    try:
        if await peer.handshake_peer():
            return
    except Exception as e:
        print(e)
    while True :
        await peer.handle_msg()
    # ctrl-c after, add better way to exit in future
    return
        

class PieceManager:
    def __init__(self, torrent, upload=False):
        self.torrent = torrent
        self.num_pieces = len(torrent.pieces)
        self.pieces_in_progress = []
        self.done_pieces = [0] * self.num_pieces  
        self.missing_pieces = list(range(self.num_pieces))
        self.num_done = 0
        self.peer_dict = {}
        if upload:
            print(f'Openning {self.torrent.file_name}')
            self.file = open(self.torrent.file_name, 'rb')
            self.data = self.file.read()
        else:
            self.file = open(self.torrent.file_name, "wb")
               
    @property
    def done(self):
        done = [i for i in self.done_pieces if i == 1]
        return len(done) >= self.num_pieces

    def reset(self, i):
        try:
            self.pieces_in_progress.remove(i)
            self.missing_pieces.append(i)
        except Exception as e:
            return

    def add_peer(self, peer_id, bitfield):
        self.peer_dict[peer_id] = bitfield

    def update_peer(self, peer_id, index: int):
        if peer_id in self.peer_dict:
            self.peer_dict[peer_id][index] = 1
    
    def remove_peer(self, peer_id):
        if peer_id in self.peer_dict:
            del self.peer_dict[peer_id]

    def have_piece(self, i):
        self.done_pieces[i] = 1
    
    def check_completed_piece(self, i):
        return self.done_pieces[i] == 1
    
    def update_to_complete(self, i):
        try:
            self.pieces_in_progress.remove(i)
            self.have_piece(i)
        except Exception as e:
            return
    
    def next_request(self, peer_id):
        if peer_id not in self.peer_dict:
            return -1
        peer_bitfields = defaultdict(int)
        if len(self.missing_pieces) > 0:
            for peer in self.peer_dict:
                for piece in range(len(self.missing_pieces)):
                    if self.peer_dict[peer][piece] == 1:
                        peer_bitfields[peer] += 1
            min_val = 100000000
            min_indx = -1
            for i, piece in enumerate(peer_bitfields.keys()):
                if peer_bitfields[piece] < min_val:
                    min_indx = i
                    min_val = peer_bitfields[piece]
            
            next_piece = self.missing_pieces.pop(min_indx)
            if next_piece is None:
                return -1
            self.pieces_in_progress.append(next_piece)
            return next_piece
                    # next_piece = self.missing_pieces.pop(piece)
                    # self.pieces_in_progress.append(next_piece)
                    # return next_piece
        
        # for piece in range(len(self.missing_pieces)):
        #     if self.peer_dict[peer_id][piece] == 1:
        #         next_piece = self.missing_pieces.pop(piece)
        #         self.pieces_in_progress.append(next_piece)
        #         return next_piece

        return -1
    
    def get_next_piece_random(self):
        print(f"attempting to grab pending piece: {self.pieces_in_progress}")
        if len(self.pieces_in_progress) > 0:
            return random.choice(self.pieces_in_progress)
            #return self.pieces_in_progress[0]

        return None
    
    def get_block(self, piece_index, offset, length):
        if piece_index > len(self.torrent.pieces):
            return None
        seek_off = piece_index * self.torrent.meta_info['info']['piece length'] + offset
        if seek_off > self.torrent.total_size:
            return None
        return self.data[seek_off:seek_off+length]
        
    
    async def add_piece(self, piece_index, data_blocks):
        if piece_index == -1:
            return 1
        combined_piece = b''.join(data_blocks)
        # checksum = self.torrent.pieces[piece_index]
        sha1_obj = sha1()
        sha1_obj.update(combined_piece)
        checksum = sha1_obj.digest()
        valid = self.torrent.pieces[piece_index]# sha1.digest()
        print(f"\n {piece_index} {checksum} {valid}\n")
        if checksum == valid:
            await self.write_to_file(piece_index * self.torrent.meta_info['info']['piece length'], combined_piece)
            self.update_to_complete(piece_index)
            self.num_done += 1
            
        else:
            self.reset(piece_index)
            return 1

        if self.done:
            print("DONE")
            self.file.close()
            if ".txt" in self.torrent.file_name:
                name = self.torrent.file_name.split('.')[0]
                os.system(f"cat {self.torrent.file_name} | tr -d '\r' > output.txt")
                os.system(f"cp output.txt {self.torrent.file_name}")
                os.system("rm output.txt")
                os._exit(0)
    
    async def write_to_file(self, offset, data):
        self.file.seek(offset)
        self.file.write(data)
