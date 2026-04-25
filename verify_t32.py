"""Verify T32 Remote API connection works end-to-end."""
import lauterbach.trace32.rcl as t32

try:
    print("→ Connecting to T32 on localhost:20000...")
    dbg = t32.connect(node="localhost", port=20000, packlen=1024)
    print("✓ Connected!")

    print("→ Sending test command...")
    dbg.cmm('PRINT "Hello from MCP setup"')
    print("✓ Check T32 AREA window — you should see 'Hello from MCP setup'")

    state = dbg.practice_state()
    print(f"✓ PRACTICE state: {state}")

    print("\n✅ ALL GOOD — ready to build the MCP server!")

except Exception as e:
    print(f"\n❌ Connection failed: {e}")
    print("\nChecklist:")
    print("  1. Is T32 currently RUNNING?")
    print("  2. Did you add RCL=NETASSIST + PORT=20000 + PACKLEN=1024 to config.t32?")
    print("  3. Did you put a blank line after PACKLEN=1024?")
    print("  4. Did you RESTART T32 after editing config.t32?")