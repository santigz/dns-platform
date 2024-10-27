FROM python:3.9

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./app /code/app

# Run directly
# CMD ["fastapi", "run", "app/main.py", "--port", "80"]

# Run after a reverse proxy
CMD ["fastapi", "run", "app/main.py", "--proxy-headers", "--port", "80"]
