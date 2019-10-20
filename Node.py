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
        self.peers = set()

        self.chain.append(self.new_block(previous_hash='1', proof=100))


    def register_peer(self, address):

        url = urlparse(address)
        self.peers.add(url.netloc)

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

        self.announce_block(new_block)
        self.chain.append(new_block)
        return new_block

    def announce_block(self, block):
        for peer in self.peers:
            url = f'http://{peer}/add_block'
            requests.post(url, data=json.dumps(block, sort_keys=True))


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
    response = {'chain': client.chain}
    return jsonify(response), 200

@app.route('/nodes/register', methods=['POST'])
def register_nodes():

    values = request.get_json()
    nodes = values.get('nodes')

    if nodes is None:
        return "Error: Please supply valid list of nodes", 400

    for node in nodes:
        client.register_peer(node)

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
    block = request.get_json()

    if not block['previous_hash'] == client.hash(client.last_block):
        client.resolve_conflicts()
        return 'previous has not valid, trying to resolve conflicts', 400
    if client.valid_proof(block):
        client.chain.append(block)
        return 201


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000, type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port

    app.run(host='0.0.0.0', port=port)






