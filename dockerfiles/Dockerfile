# docker build -f dockerfiles/Dockerfile-base -t noatgnu/cupcake-base:0.1.0 .
FROM noatgnu/cupcake-base:0.1.0


#RUN git clone https://github.com/ggerganov/whisper.cpp.git
#WORKDIR /app/whisper.cpp
#RUN /app/whisper.cpp/models/download-ggml-model.sh base.en
#RUN cmake -B build
#RUN cmake --build build --config Release -j $(nproc)

#WORKDIR /app
#RUN apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 8000
CMD ["gunicorn","--workers=4", "cupcake.asgi:application", "--bind", "0.0.0.0:8000","--timeout", "300", "-k", "uvicorn.workers.UvicornWorker"]