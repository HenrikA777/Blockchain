import hashlib
import json
import random
import sys
from time import time
from urllib.parse import urlparse
from uuid import uuid4

import requests
from flask import Flask, jsonify, request


class Node:
    difficulty = '0000'

    def __init__(self):
        self.transactions = []
        self.chain = []
        self.peers = []

        self.chain.append(self.new_block(previous_hash='1', proof=100))


    def register_peer(self, address):

        url = urlparse(address)
        self.peers.append(url.netloc)

    def valid_chain(self, chain):

        last_block = chain[0]
        index = 1

        while index < len(chain):
            block = chain[index]

            if block['previous_hash'] != self.hash(last_block):
                return False

            if not self.valid_proof(block):
                return False

            last_block = block
            index += 1

        return True


    def new_block(self, proof, previous_hash = None):
        if previous_hash == None:
            previous_hash = self.hash(self.chain[-1])
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time(),
            'transactions': self.transactions,
            'proof': proof,
            'previous_hash': previous_hash
        }

        self.transactions = []

        return block

    def new_transaction(self, sender, data):

        self.transactions.append({
            'sender': sender,
            'data': data
        })

        return self.last_block['index'] + 1

    def add_peer(self, node):
        duplicate = True
        announce = False
        if not node == request.host:
            duplicate = False
            for peer in self.peers:
                if node == peer:
                    duplicate = True
        if not duplicate:
            self.peers.append(node)
            announce = True

        if len(self.peers) < 1:
            if not node == request.host:
                self.peers.append(node)
                announce = True
        return announce

    @property
    def last_block(self):
        return self.chain[-1]

    @staticmethod
    def hash(block):

        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self):

        proof = 0
        last_block = self.last_block
        new_block = self.new_block(proof)
        while self.valid_proof(new_block) is False:
            if not last_block == self.last_block:
                return None
            new_block['proof'] += 1


        self.chain.append(new_block)
        self.announce_block(new_block)
        return new_block

    def announce_block(self, block):
        for peer in self.peers:
            url = f'http://{peer}/add_block'
            requests.post(url, data=json.dumps(block))


    @staticmethod
    def valid_proof(block):

        guess_hash = Node.hash(block)
        return guess_hash.startswith(Node.difficulty)

    def resolve_conflicts(self):

        new_chain = None
        max_length = len(self.chain)

        for node in self.peers:
            response = requests.get(f'http://{node}/chain')

            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                if length > max_length and self.valid_chain(chain):
                    max_length = length
                    new_chain = chain

        if new_chain:
            self.chain = new_chain
            return True

        return False

app = Flask(__name__)
node_identifier = str(uuid4()).replace('-', '')
client = Node()

@app.route('/chain', methods=['GET'])
def get_chain():
    response = {'chain': client.chain,
                'length': len(client.chain)}
    return jsonify(response), 200

@app.route('/nodes', methods=['GET'])
def get_nodes():
    response = {'peers': client.peers}
    return jsonify(response), 200

@app.route('/nodes/register', methods=['POST'])
def register_nodes():

    values = request.data.decode('utf8').replace("'", '"').replace("\\", "")
    data = json.loads(values)
    arr = []
    for a in data["nodes"]:
        arr.append(a)


    if len(arr) < 1:
        return "Error: Please supply valid list of nodes", 400
    announce = False
    for node in arr:
        print(node)
        if client.add_peer(node):
            announce = True
    if announce:
        if announce:
            for peer in client.peers:
                if not peer == request.remote_addr:
                    message = {"nodes": client.peers}
                    url = f'http://{peer}/nodes/register'
                    requests.post(url, data=json.dumps(message, sort_keys=True))

    response = {
        'message': 'New peers added',
        'total_peers': list(client.peers)
    }
    return jsonify(response), 201

@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = client.resolve_conflicts()

    if replaced:
        response = {
            'message': 'chain replaced',
            'new_chain': client.chain
        }
    else:
        response = {
            'message': 'node chain is authoritative',
            'chain': client.chain
        }

    return jsonify(response), 200

@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()

    required_fields = ['sender', 'data']
    if not all(k in values for k in required_fields):
        return 'missing fields', 400

    index = client.new_transaction(values['sender'], values['data'])

    response = {'message': f'transaction will be added to block {index}'}
    return jsonify(response), 201

@app.route('/mine', methods=['GET'])
def mine():
    client.new_transaction(node_identifier, 'mined a block')
    new_block = client.proof_of_work()
    if new_block is None:
        response = {
            'message': 'new block received from peer'
        }
    else:
        response = {
            'message': 'new block forged',
            'block': new_block
        }
    return jsonify(response), 201

@app.route('/add_block', methods=['POST'])
def validate_add_block():
    block = request.get_json(force=True)
    print(block)

    if not block['previous_hash'] == client.hash(client.last_block):
        client.resolve_conflicts()
        return 'previous has not valid, trying to resolve conflicts', 400
    if client.valid_proof(block):
        client.chain.append(block)
        return 'Block accepted', 201

@app.route('/start', methods=['GET'])
def start():
    ip = request.host.split(':')[0]
    org_port = 5000
    port = request.host.split(':')[1]
    org_node = f'{ip}:{org_port}'
    this_node = f'{ip}:{port}'
    if not port == org_port:
        client.add_peer(org_node)
        url = f'http://{org_node}/nodes'
        arr = []
        arr.append(this_node)
        message = {"nodes": arr}
        print(message)
        requests.post(url + '/register', data=json.dumps(message, sort_keys=True))
        response = requests.get(url).json()
        print(response)
        for node in response['peers']:
            print(node)
            client.add_peer(node)
    return jsonify(this_node), 200


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000, type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port




    app.run(host='0.0.0.0', port=port)

