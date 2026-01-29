#!/usr/bin/env python3
"""
InsanusChat CLI - Complete API Management Tool
"""
import asyncio
import httpx
import sys
import os
import argparse
from typing import Optional

# Color codes
class C:
    H = '\033[95m'; B = '\033[94m'; G = '\033[92m'; Y = '\033[93m'
    R = '\033[91m'; E = '\033[0m'; BOLD = '\033[1m'; GRAY = '\033[90m'

class CLI:
    def __init__(self, url="http://localhost:8000"):
        self.url = url.rstrip('/'); self.token = None; self.email = None
        self.chat_id = None; self.chat_title = None; self.client = httpx.AsyncClient(timeout=30.0)
    
    def p_h(self, t): print(f"\n{C.H}{C.BOLD}{'='*70}\n{t:^70}\n{'='*70}{C.E}\n")
    def p_s(self, t): print(f"{C.G}✓ {t}{C.E}")
    def p_e(self, t): print(f"{C.R}✗ {t}{C.E}")
    def p_i(self, t): print(f"{C.B}ℹ {t}{C.E}")
    def hdr(self): return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"} if self.token else {"Content-Type": "application/json"}
    def status(self): return f"{C.G}{self.email}{C.E}" + (f" | Chat: {self.chat_title}" if self.chat_id else "") if self.email else f"{C.GRAY}Not logged in{C.E}"
    
    async def register(self):
        self.p_h("Register"); e = input(f"{C.B}Email: {C.E}").strip(); p = input(f"{C.B}Password: {C.E}").strip(); n = input(f"{C.B}Name: {C.E}").strip()
        if not all([e, p, n]): return self.p_e("All fields required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/auth/register", json={"email": e, "password": p, "display_name": n})
            self.p_s(f"Registered! ID: {r.json().get('data', {}).get('user_id')}") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def login(self):
        self.p_h("Login"); e = input(f"{C.B}Email: {C.E}").strip(); p = input(f"{C.B}Password: {C.E}").strip()
        if not all([e, p]): return self.p_e("Email and password required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/auth/login", json={"email": e, "password": p})
            if r.status_code == 200:
                d = r.json().get('data', {}); self.token = d.get('access_token'); self.email = e; self.p_s(f"Logged in as {e}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def logout(self): self.token = None; self.email = None; self.chat_id = None; self.chat_title = None; self.p_s("Logged out")
    
    async def profile(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/auth/", headers=self.hdr())
            if r.status_code == 200:
                u = r.json().get('data', {}); self.p_h("Profile"); print(f"Email: {u.get('email')}\nName: {u.get('display_name')}\nID: {u.get('id')}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def list_apikeys(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/apikeys/", headers=self.hdr())
            if r.status_code == 200:
                ks = r.json().get('data', []); self.p_h(f"API Keys ({len(ks)})")
                for k in ks: print(f"\nID: {k.get('_id')}\n  Provider: {k.get('provider')}\n  Label: {k.get('label', 'N/A')}\n  Active: {k.get('active')}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def add_apikey(self):
        if not self.token: return self.p_e("Login first")
        self.p_h("Add API Key"); p = input(f"{C.B}Provider: {C.E}").strip(); k = input(f"{C.B}Key: {C.E}").strip(); l = input(f"{C.B}Label: {C.E}").strip()
        if not all([p, k]): return self.p_e("Provider and key required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/apikeys/", headers=self.hdr(), json={"provider": p, "encrypted_key": k, "label": l or None})
            self.p_s(f"Added! ID: {r.json().get('data', {}).get('_id')}") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def del_apikey(self, id):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.delete(f"{self.url}/api/v1/apikeys/?api_key_id={id}", headers=self.hdr())
            self.p_s("Deleted") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def list_mcps(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/resources/", headers=self.hdr())
            if r.status_code == 200:
                ms = r.json().get('data', {}).get('mcps', []); self.p_h(f"MCPs ({len(ms)})")
                for m in ms: print(f"\nID: {m.get('_id')}\n  Name: {m.get('name')}\n  Transport: {m.get('transport', 'stdio')}\n  Active: {m.get('active')}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def add_mcp(self):
        if not self.token: return self.p_e("Login first")
        self.p_h("Add MCP"); n = input(f"{C.B}Name: {C.E}").strip(); t = input(f"{C.B}Transport [stdio]: {C.E}").strip() or "stdio"
        pl = {"name": n, "transport": t}
        if t == "stdio": s = input(f"{C.B}Script Path: {C.E}").strip(); c = input(f"{C.B}Command [auto]: {C.E}").strip(); pl["local_script_path"] = s; (pl.update({"command": c}) if c else None)
        else: e = input(f"{C.B}Endpoint: {C.E}").strip(); pl["endpoint"] = e
        if not n: return self.p_e("Name required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/resources/mcps", headers=self.hdr(), json=pl)
            self.p_s(f"Added! ID: {r.json().get('data', {}).get('_id')}") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def del_mcp(self, id):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.delete(f"{self.url}/api/v1/resources/mcps?mcp_id={id}", headers=self.hdr())
            self.p_s("Deleted") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def list_snippets(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/resources/", headers=self.hdr())
            if r.status_code == 200:
                ss = r.json().get('data', {}).get('code_snippets', []); self.p_h(f"Snippets ({len(ss)})")
                for s in ss: print(f"\nID: {s.get('_id')}\n  Name: {s.get('name')}\n  Lang: {s.get('language')}\n  Code: {s.get('code', '')[:50]}...")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def add_snippet(self):
        if not self.token: return self.p_e("Login first")
        self.p_h("Add Snippet"); n = input(f"{C.B}Name: {C.E}").strip(); l = input(f"{C.B}Lang (python/javascript): {C.E}").strip(); d = input(f"{C.B}Desc: {C.E}").strip()
        print(f"{C.B}Code (Enter twice to finish):{C.E}"); lines = []
        while True: ln = input(); ((lines.pop() if not ln and lines and not lines[-1] else None), break) if not ln and lines else lines.append(ln)
        code = "\n".join(lines)
        if not all([n, l, code]): return self.p_e("Name, lang, and code required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/resources/snippets", headers=self.hdr(), json={"name": n, "language": l, "code": code, "description": d or None})
            self.p_s(f"Added! ID: {r.json().get('data', {}).get('_id')}") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def del_snippet(self, id):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.delete(f"{self.url}/api/v1/resources/snippets?snippet_id={id}", headers=self.hdr())
            self.p_s("Deleted") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def list_agents(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/agents/", headers=self.hdr())
            if r.status_code == 200:
                ag = r.json().get('data', []); self.p_h(f"Agents ({len(ag)})")
                for a in ag: print(f"\nID: {a.get('_id')}\n  Name: {a.get('name')}\n  Active: {a.get('active')}\n  Model: {a.get('model_selected', 'N/A')}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def add_agent(self):
        if not self.token: return self.p_e("Login first")
        self.p_h("Add Agent"); n = input(f"{C.B}Name: {C.E}").strip(); d = input(f"{C.B}Desc: {C.E}").strip(); m = input(f"{C.B}Model [gemini-1.5-flash]: {C.E}").strip() or "gemini-1.5-flash"
        print(f"{C.B}Prompt (Enter twice):{C.E}"); prs = []
        while True: ln = input(); (break if not ln and prs else (prs.append(ln) if ln else None))
        if not n: return self.p_e("Name required")
        try:
            r = await self.client.post(f"{self.url}/api/v1/agents/", headers=self.hdr(), json={"name": n, "description": d or None, "system_prompt": prs, "model_selected": m, "snippets": []})
            self.p_s(f"Added! ID: {r.json().get('data', {}).get('_id')}") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def del_agent(self, id):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.delete(f"{self.url}/api/v1/agents/?agent_id={id}", headers=self.hdr())
            self.p_s("Deleted") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def list_chats(self):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/chats/", headers=self.hdr())
            if r.status_code == 200:
                cs = r.json().get('data', []); self.p_h(f"Chats ({len(cs)})")
                for c in cs: sel = f" {C.G}← Current{C.E}" if c.get('_id') == self.chat_id else ""; print(f"\nID: {c.get('_id')}{sel}\n  Title: {c.get('title', 'Untitled')}\n  Messages: {c.get('message_count', 0)}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def new_chat(self):
        if not self.token: return self.p_e("Login first")
        self.p_h("New Chat"); t = input(f"{C.B}Title: {C.E}").strip(); m = input(f"{C.B}Message: {C.E}").strip(); await self.list_agents(); a = input(f"\n{C.B}Agent ID: {C.E}").strip()
        pl = {}; (pl.update({"title": t}) if t else None); (pl.update({"agent_id": a}) if a else None); (pl.update({"initial_message": m}) if m else None)
        try:
            r = await self.client.post(f"{self.url}/api/v1/chats/", headers=self.hdr(), json=pl)
            if r.status_code == 200: c = r.json().get('data', {}); self.chat_id = c.get('_id'); self.chat_title = c.get('title', 'Untitled'); self.p_s(f"Created! ID: {self.chat_id}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def sel_chat(self, id): self.chat_id = id; self.chat_title = f"Chat {id[:8]}"; self.p_s(f"Selected: {id}")
    
    async def del_chat(self, id):
        if not self.token: return self.p_e("Login first")
        try:
            r = await self.client.delete(f"{self.url}/api/v1/chats/{id}", headers=self.hdr())
            (setattr(self, 'chat_id', None), setattr(self, 'chat_title', None)) if self.chat_id == id and r.status_code == 200 else None
            self.p_s("Deleted") if r.status_code == 200 else self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def send(self, msg):
        if not self.token: return self.p_e("Login first")
        if not self.chat_id: return self.p_e("No chat selected")
        try:
            r = await self.client.post(f"{self.url}/api/v1/chats/{self.chat_id}/messages", headers=self.hdr(), json={"content": msg})
            self.p_s("Sent!") if r.status_code == 200 else self.p_e(f"Failed: {r.text}"); print(f"{C.BOLD}You:{C.E} {msg}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    async def history(self):
        if not self.token or not self.chat_id: return self.p_e("Login and select chat first")
        try:
            r = await self.client.get(f"{self.url}/api/v1/chats/{self.chat_id}/messages", headers=self.hdr())
            if r.status_code == 200:
                msgs = r.json().get('data', []); self.p_h(f"History - {self.chat_title}")
                for m in msgs: role = m.get('role', 'user'); print(f"\n{C.B if role == 'user' else C.G}{role.title()}{C.E}: {m.get('content', '')}")
            else: self.p_e(f"Failed: {r.text}")
        except Exception as ex: self.p_e(f"Error: {ex}")
    
    def help(self):
        self.p_h("Commands"); print(f"""
Auth: register, login, logout, profile
API Keys: apikeys, apikey add, apikey delete <id>
MCPs: mcps, mcp add, mcp delete <id>
Snippets: snippets, snippet add, snippet delete <id>
Agents: agents, agent add, agent delete <id>
Chats: chats, chat new, chat select <id>, chat delete <id>
Messages: send <msg>, history
Util: clear, status, help, quit/exit
        """)
    
    async def run(self):
        self.p_h("InsanusChat CLI"); self.p_i(f"Connected: {self.url}"); print(f"{C.GRAY}Type 'help'{C.E}\n")
        while True:
            try:
                cmd = input(f"\n{self.status()}\n{C.BOLD}>{C.E} ").strip(); parts = cmd.split(maxsplit=2); c = parts[0].lower() if parts else ""
                if not c: continue
                if c == "register": await self.register()
                elif c == "login": await self.login()
                elif c == "logout": await self.logout()
                elif c == "profile": await self.profile()
                elif c == "apikeys": await self.list_apikeys()
                elif c == "apikey": (await self.add_apikey() if len(parts) == 2 and parts[1] == "add" else (await self.del_apikey(parts[2]) if len(parts) == 3 and parts[1] == "delete" else self.p_e("Usage: apikey <add|delete> [id]")))
                elif c == "mcps": await self.list_mcps()
                elif c == "mcp": (await self.add_mcp() if len(parts) == 2 and parts[1] == "add" else (await self.del_mcp(parts[2]) if len(parts) == 3 and parts[1] == "delete" else self.p_e("Usage: mcp <add|delete> [id]")))
                elif c == "snippets": await self.list_snippets()
                elif c == "snippet": (await self.add_snippet() if len(parts) == 2 and parts[1] == "add" else (await self.del_snippet(parts[2]) if len(parts) == 3 and parts[1] == "delete" else self.p_e("Usage: snippet <add|delete> [id]")))
                elif c == "agents": await self.list_agents()
                elif c == "agent": (await self.add_agent() if len(parts) == 2 and parts[1] == "add" else (await self.del_agent(parts[2]) if len(parts) == 3 and parts[1] == "delete" else self.p_e("Usage: agent <add|delete> [id]")))
                elif c == "chats": await self.list_chats()
                elif c == "chat": (await self.new_chat() if len(parts) == 2 and parts[1] == "new" else (await self.sel_chat(parts[2]) if len(parts) == 3 and parts[1] == "select" else (await self.del_chat(parts[2]) if len(parts) == 3 and parts[1] == "delete" else self.p_e("Usage: chat <new|select|delete> [id]"))))
                elif c == "send": (await self.send(" ".join(parts[1:])) if len(parts) >= 2 else self.p_e("Usage: send <msg>"))
                elif c == "history": await self.history()
                elif c == "clear": os.system('clear' if os.name != 'nt' else 'cls')
                elif c == "status": (self.p_i(f"User: {self.email}\nChat: {self.chat_title or 'None'}") if self.email else self.p_e("Not logged in"))
                elif c == "help": self.help()
                elif c in ("quit", "exit"): self.p_i("Goodbye!"); break
                else: self.p_e(f"Unknown: {c}. Type 'help'")
            except KeyboardInterrupt: print(); self.p_e("Use 'quit' to exit")
            except Exception as ex: self.p_e(f"Error: {ex}")
        await self.client.aclose()

async def main():
    p = argparse.ArgumentParser(); p.add_argument("--url", default="http://localhost:8000"); args = p.parse_args()
    await CLI(args.url).run()

if __name__ == "__main__": asyncio.run(main())
