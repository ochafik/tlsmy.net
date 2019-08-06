#!/usr/bin/env python3

import dnslib
import dnslib.label
import dnslib.server
import logging
import os
import re
import redis
import signal
import time

BASE36_SHA256_HASH = re.compile(r"[0-9a-z]{51}")

class Resolver(object):
    def __init__(self, domain, server_ip):
        self.domain = domain
        self.server_ip = server_ip
        self.redis = redis.Redis()

    def resolve(self, request, handler):
        reply = request.reply()
        qname = request.q.qname

        # Refuse queries thaat are not for our domain
        if not qname.matchSuffix(self.domain):
            reply.header.rcode = dnslib.RCODE.REFUSED
            return reply 

        # Answer questions about the root domain name
        # TODO(supersat): We don't need to implement this, right?
        if qname == self.domain:
            if request.q.qtype == dnslib.QTYPE.A:
                reply.add_answer(dnslib.RR(
                    qname,
                    dnslib.QTYPE.A,
                    ttl=300,
                    rdata=self.server_ip))
            return reply

        uname = qname.stripSuffix(self.domain)
        subdomain = uname._decode(uname.label[-1]).lower()
        if BASE36_SHA256_HASH.match(subdomain):
            if len(uname.label) == 2 and \
                uname.label[-2] == b'_acme-challenge' and \
                (request.q.qtype == dnslib.QTYPE.TXT or \
                request.q.qtype == dnslib.QTYPE.ANY):
                txt = self.redis.get('acmetxtchal:{}'.format(subdomain))
                if txt:
                    reply.add_answer(dnslib.RR(
                        qname,
                        dnslib.QTYPE.TXT,
                        ttl=300,
                        rdata=dnslib.TXT(txt)
                    ));
                else:
                    reply.header.rcode = dnslib.RCODE.NXDOMAIN
            elif len(uname.label) == 5 and \
                (request.q.qtype == dnslib.QTYPE.A or \
                request.q.qtype == dnslib.QTYPE.ANY):
                try:
                    ip = tuple(map(int, uname.label[0:4]))
                    reply.add_answer(dnslib.RR(
                        qname,
                        dnslib.QTYPE.A,
                        ttl=300,
                        rdata=dnslib.A(ip)
                    ))
                except:
                    reply.header.rcode = dnslib.RCODE.NXDOMAIN
            else:
                reply.header.rcode = dnslib.RCODE.NXDOMAIN
            return reply

        reply.header.rcode = dnslib.RCODE.NXDOMAIN
        return reply

def handle_sig(signum, frame):
    logging.info('pid=%d, got signal: %s, stopping...', os.getpid(), signal.Signals(signum).name)
    exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_sig)

    domain = dnslib.label(os.getenv('DOMAIN', 'tlsmy.net'))
    server_ip = dnslib.A(os.getenv('SERVER_IP', '127.0.0.1'))
    port = int(os.getenv('PORT', 53))
    resolver = Resolver(domain, server_ip)
    udp_server = dnslib.server.DNSServer(resolver, port=port)
    tcp_server = dnslib.server.DNSServer(resolver, port=port, tcp=True)

    logging.info('starting DNS server on port %d', port)
    udp_server.start_thread()
    tcp_server.start_thread()

    try:
        while udp_server.isAlive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass