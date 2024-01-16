# BitTorrent Report
By: Cody Li, Shreyas Pant, and Aditya Sharda

## Feature List	
Communication with the tracker using HTTP GET request to get list of peers in the swarm
Has compact peer list support
Being able to download the debian ISO file
The implementation of the rarest first strategy
Starting the client in upload mode allowing peers to request data
Direct download without need of tracker when peer IP address and port are known
Utilizes the End-Game strategy to quickly get remaining files when more than 85% of pieces have been received

## Design + Implementation Choices
A major design choice we made was the use of Python’s built-in Asynchronous I/O library. It allowed us to use async/await to more efficiently complete tasks and reduce downtimes. We chose to use async and await as it was an easier alternative to threads and generally made our code easier to understand and debug. 

We also chose to take an object oriented approach by making object classes such as Peers as this allowed us to have multiple async tasks/workers running at once. For each peer we received from the tracker, we created a new Peer object. Each Peer object had their own instance variables so that we could efficiently have each peer request a new piece that our client did not have from the peers they were connected to. 

Our implementation also utilized a single central PieceManager object that formed the centerpiece of all Peers. Each peer had to communicate with the PieceManager to get the next piece index to request; check piece checksum and write to file; and fetch block from file. Having only a single  PieceManager tying all our async Peers together prevented us from running into data races.

## Obstacles and Overcomings
In the initial stages of connecting to peers and the reference server, we ran into a bug where a peer id within the initial response message was causing a problem with how we were parsing the initial response. Our initial logic was to split on a ‘\n’; however, since this peer id was getting hashed as a new line character, it prevented us from parsing the response correctly and thus led to us being unable to connect on the client side. To combat this, we seeked past the initial HTTP header within our logic to look for ‘d8:’ which represents the first 3 characters of the tracker’s response’s payload.. 
	
A problem that we encountered was that there were multiple carriage return characters (‘\r’) and additional new line characters (‘\n’) being written to our output file. We attempted to resolve this by changing the way we were writing to the output file. Initially, we were using the os.lseek() and os.write() functions  to accomplish this, but we then changed to python’s file reading functions (seek() and write()) to write to the file.

One of the biggest problems we ran into was towards the end of our download, the client would hang due to slow seeders and receiving messages back at a very slow rate, this was especially the case for larger files like the debian iso file. To work around this, we implemented a timeout feature as well as the End-Game strategy. The timeout would check if a peer has been waiting for a request piece index for too long. If it has, reset the piece, and let that peer sleep for a few seconds allowing another peer who potentially can provide the blocks for the pieces faster. The End-Game strategy we implemented also helps for this case as it allows a free peer to grab a piece in our pending requests list to request it from its peer. This allowed our downloads to speed up dramatically near the end.




## Known Bugs and Future Work
A known bug/issue in our implementation relates to how the occasional bad list of peers who are not actually seeders that we receive lead to hanging and stalling during the start of the download process. Due to this issue, we may have to rerun our program on the debian ISO torrent a few times before we can fully download it.
We also did not get a chance to implement a better way to exit the client after it is done. At the current moment, we will have to force close using Ctrl + C to close when we get messages notifying that the download has completed. We hope in the future when we revisit this project, we will implement a better exit method either automatically stopping all async tasks or adding a command line interface to input an exit command.
Our client tends to receive excess piece packets even after the download has completed due to use implementing the End-Game strategy resulting in our client sending the same requests to multiple clients towards the end of our download. We did not have an effective way to cancel the extra requests sent during End-Game but we hope to address it in the future by potentially keeping track of a list of block requests that have not been answered yet.

## Collaboration
Completing this project was a joint effort amongst all members of our team. We would join zoom calls everyday to debug and think of ways to implement the BitTorrent client together. Utilizing a peer-programming structure, our group of three would have a dedicated shared screen on one of our devices where we all had remote control. With the collision of ideas on implementation, we were able to overcome challenges mentioned above and increase productivity as we were always on the same page. A bonus was avoiding merge conflicts; however, we still prioritized proper CI/CD structure and utilized branches for certain features in order to prevent issues from arising when testing specific features. Overall, the design and functionality of the project was done collaboratively and there was never a discrepancy within our effort levels as we all understood the gravity of this project. 

## Running
```
python3 main.py <torrent-file> -d <download> -a <address:port>
```
