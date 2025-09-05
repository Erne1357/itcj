from itcj import create_app
app, socketio= create_app()

# Para desarrollo local 
if __name__ == "__main__":
    socketio.run(host="0.0.0.0", port=8000, debug=True)
