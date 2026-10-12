"""Hosted read gateway: the only path from the hosted (Vercel) instance to this machine's PostgreSQL.

    Vercel  --HTTPS-->  Cloudflare edge (Access service token)  --tunnel (outbound from this laptop)-->  cloudflared
            --http://127.0.0.1:8787-->  gateway (signed requests, fixed read-only routes)  -->  PostgreSQL as mospi_reader (hosted_* views)

PostgreSQL itself is never exposed through the tunnel.  See docs/deployment/CLOUDFLARE_TUNNEL.md.
"""
