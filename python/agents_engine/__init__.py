"""Finding scheduled agents, talking to them, and serving what they say over HTTP.

`discover` reaches the agents. `routes` is the HTTP side: the handler any Python
server can mount to answer /state.json, /agents/<key>, /apply and /run.
"""
