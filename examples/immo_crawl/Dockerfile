# As Scrapy runs on Python, I choose the official Python 3 Docker image.
FROM python:3
 
# Set the working directory to /usr/src/app.
WORKDIR /usr/src/app

#install some dependencies 
RUN apt-get update && \ 
	apt-get install -y libpq-dev
 
# Copy the file from the local host to the filesystem of the container at the working directory.
COPY requirements.txt ./
 
# Install Scrapy specified in requirements.txt.
RUN pip3 install --no-cache-dir -r requirements.txt

 
# Copy the project source code from the local host to the filesystem of the container at the working directory.
COPY . .
EXPOSE 6800
RUN mkdir -p /etc/scrapyd 
COPY scrapyd.conf /etc/scrapyd/scrapyd.conf 
# Run the crawler when the container launches.
#CMD [ "python3", "./setup.py" ]
CMD  bash start.sh
#CMD scrapy crawl  immoscout 
#CMD scrapy runspider immo_crawl/spiders/immoscout_spider.py
