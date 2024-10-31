FROM python:3.10
RUN apt-get update && apt-get install -y bind9 dnsutils

WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY . /code/
# COPY ./templates /code/templates
# COPY ./static /code/static
# COPY ./app /code/app

# Run directly
# CMD ["fastapi", "run", "app/main.py", "--port", "80"]

# Run after a reverse proxy
CMD ["fastapi", "run", "app/main.py", "--proxy-headers", "--port", "80"]
