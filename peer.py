import asyncio
import struct
import sys
import bitstring
import math
import time

# 16kb?
BUFF_SIZE = 16384

# Message IDs
CHOKE = 0
UNCHOKE = 1
INTERESTED = 2
NOTINTERESTED = 3
HAVE = 4
BITFIELD = 5
REQUEST = 6
PIECE = 7
CANCEL = 8
UNKNOWN = -1 # custom ID

class Peer:
    def __init__(self, our_id, manager, info_hash, peer_ip, peer_port):
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.our_id = our_id
        self.peer_id = None
        self.piece_manager = manager
        self.info_hash = info_hash
        self.stopped = False
        self.reader = None
        self.writer = None

        self.am_choked = True
        self.am_interested = False
        self.peer_choked = True
        self.peer_interested = False
        
        self.blocks_expected = (math.ceil(self.piece_manager.torrent.meta_info['info']['piece length'] // BUFF_SIZE))
        self.requested = -1
        self.blocks = [0]*self.blocks_expected
        self.num_recv = 0
        self.requested_time = None

    async def handshake_peer(self):
        try:
            conn = asyncio.open_connection(self.peer_ip, self.peer_port)
            self.reader, self.writer = await asyncio.wait_for(conn, timeout=20)
            # Handshake
            if type(self.info_hash) is str:
                self.info_hash = self.info_hash.encode()
            if type(self.our_id) is str:
                self.our_id = self.our_id.encode()

            message = struct.pack(
                '>B19s8x20s20s',
                19,
                b'BitTorrent protocol',
                self.info_hash,
                self.our_id)
            self.writer.write(message)
            await self.writer.drain()

            resp = await self.reader.read(68)

            if len(resp) < 68:
                raise Exception("failed to recv handshake")
            unpacked = struct.unpack('>B19s8s20s20s', resp)
            #if not unpacked[3] == self.info_hash:
                #raise Exception("info_hash mismatch")
            self.peer_id = unpacked[4]
            return 0
        except Exception as e:
            print(e)
            return 1
        
    def set_as_upload(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def handle_msg(self):

        try:
            msg = await asyncio.wait_for(self.next_message(), timeout=10)
        except Exception as e:
            return
        try:
            if msg['id'] == CHOKE:
                self.am_choked = True
            elif msg['id'] == UNCHOKE:
                self.am_choked = False
            elif msg['id'] == INTERESTED:
                self.peer_interested = True
            elif msg['id'] == NOTINTERESTED:
                self.peer_interested = False
            elif msg['id'] == HAVE:
                # update peer's entry in manager to show they have new piece with the index provided
                
                self.piece_manager.update_peer(self.peer_id, msg['index'])
                #pass
            elif msg['id'] == BITFIELD:
                # add peer to manager with initial bitfield
                
                self.piece_manager.add_peer(self.peer_id, msg['bitfield'])
                # Send interested
                message = struct.pack('>Ib', 1, 2)
                self.writer.write(message)
                await self.writer.drain()
                self.am_interested = True
                
                #pass
            elif msg['id'] == REQUEST:
                # get block from file manager or whatever is managing the file being uploaded
                block = self.piece_manager.get_block(msg['index'], msg['begin'], msg['len'])
                if block:
                    print(f'got block from piece {msg["index"]}')
                    block_len = len(block)
                    message = struct.pack(f'>IbII{block_len}s', 9 + block_len, PIECE, msg['index'], msg['begin'], block)
                    self.writer.write(message)
                    await self.writer.drain()
                pass
            elif msg['id'] == PIECE:
                # add block into to piece manager
                # reset timeout every time we get a piece back
                if self.piece_manager.num_done <= self.piece_manager.num_pieces:
                    print(f'Pieces Done: {self.piece_manager.num_done} Out of {self.piece_manager.num_pieces} Pending {self.piece_manager.pieces_in_progress}')
                else:
                    print("Task Already Finished, Feel Free to Exit")
                self.blocks[msg['begin'] // BUFF_SIZE] = msg['block']
                self.num_recv += 1
                print(f"{self.requested}\n")
                if self.requested == msg['index']:
                    self.requested_time = time.time()
                if self.num_recv >= self.blocks_expected:
                    ret = await self.piece_manager.add_piece(self.requested, self.blocks)
                    self.requested = -1
                    self.num_recv = 0
                    self.requested_time = None
                        
                #pass
            elif msg['id'] == CANCEL:
                # don't send requested block
                # maybe set up a requests queue for this in future
                pass

        except Exception as e:
            print(e)

        # requesting part
        if not self.am_choked:
            if self.am_interested:
                if self.requested < 0:
                    
                    # request block here
                    next_req = self.piece_manager.next_request(self.peer_id)
                    random = False
                    if (next_req is None or next_req < 0) and (self.piece_manager.num_done / float(self.piece_manager.num_pieces) > 0.85):
                        
                        random = True
                        next_req = self.piece_manager.get_next_piece_random()
                        if next_req is None:
                            return
                        print("grabbed pending piece")
                        
                    block_off = 0
                    
                    piece_len = self.piece_manager.torrent.meta_info['info']['piece length']
                    try:
                        # send request for piece
                        while block_off < piece_len:
                            req_size = BUFF_SIZE
                            if piece_len - block_off < req_size:
                                req_size = piece_len - block_off
                            message = struct.pack('>IbIII', 13, REQUEST, next_req, block_off, req_size)
                            
                            block_off += req_size
                            self.writer.write(message)
                            await self.writer.drain()
                        self.requested_time = time.time()
                        print(f'sent requests for piece {next_req}')
                    except Exception as e:
                        print(f'failed to send requests for piece {next_req}')
                        if not random:
                            self.piece_manager.reset(next_req)
                            return
                        
                    self.requested = next_req
        
        # timeout check
        if self.requested_time != None and self.requested != -1:
            curr_time = time.time()
            if int(curr_time - self.requested_time) > 10:
                self.piece_manager.reset(self.requested)
                print(f'{self.requested} timed out')
                self.requested = -1
                self.num_recv = 0
                self.requested_time = None
                await asyncio.sleep(5) #let other peers try
        return 0



    async def close(self):
        self.stopped = True
        if self.writer:
            self.writer.close()

    async def next_message(self):
        msg_len = 0
        while True:
            resp = await self.reader.read(4)
            if len(resp) >= 4:
                msg_len = struct.unpack('>I', resp[0:4])[0]
            if msg_len > 0:
                break


        resp = await self.reader.readexactly(msg_len)
        data = {} 
        #print('got msg')

        msg_id = int(resp[0])
        data['id'] = msg_id

        if msg_id == CHOKE:
            return data
        elif msg_id == UNCHOKE:
            return data
        elif msg_id == INTERESTED:
            return data
        elif msg_id == NOTINTERESTED:
            return data
        elif msg_id == HAVE:

            unpacked = struct.unpack('>bI', resp)
            data['index'] = unpacked[1]
            return data
        
        elif msg_id == BITFIELD:

            data['bitfield'] = bitstring.BitArray(bytes=resp[1:]) # everything after 

            #bits = bin(int.from_bytes(unpacked[2], byteorder=sys.byteorder))
            #bits = bits[2:]
            #byte_arr = [bits[i:i+8] for i in range(0, len(bits), 8)]
            #byte_arr.reverse()
            #data['bitfield'] = ''.join(byte_arr)
            return data
        
        elif msg_id == REQUEST:

            unpacked = struct.unpack('>bIII', resp)
            data['index'] = int(unpacked[1])
            data['begin'] = int(unpacked[2])
            data['len'] = int(unpacked[3])
            print(f'got request for piece {int(unpacked[1])}')
            return data
        
        elif msg_id == PIECE:

            piece_len = msg_len
            unpacked = struct.unpack(f'>bII{piece_len - 9}s', resp)
            data['index'] = int(unpacked[1])
            data['begin'] = int(unpacked[2])
            data['block'] = unpacked[3]
            
            return data
        
        elif msg_id == CANCEL:

            unpacked = struct.unpack('>bIII', resp)
            data['index'] = int(unpacked[1])
            data['begin'] = int(unpacked[2])
            data['len'] = int(unpacked[3])
            return data
        
        else:
            data['id'] = UNKNOWN #just ignores

        return data