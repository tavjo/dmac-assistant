# NExtSEEK

NExtSEEK is an in-house web wrapper over the SEEK system which provides advanced features relevant to our data management team. NExtSEEK is a Django application and heavily interfaces with the SEEK MySQL database.

NExtSEEK should be run on an enterprise Linux system, such as Rocky Linux or Red Hat Enterprise Linux.

The installation instructions also assume that NExtSEEK is running on the same VM as SEEK is, and that the user has followed the installation instructions in the previous SEEK installation section.

## [hashtag](#page-iGwqsCLolxfAjNlhpurd-system-packages) System Packages

**The entirety of this section should be run as the** `service-account` **user, or any user account with** `sudo` **access, unless otherwise specified.**

The `mysqlclient` Python package won't work on RHEL 9 unless you install `mariadb-connector-c-devel`, so install it using the system package manager:

## [hashtag](#page-iGwqsCLolxfAjNlhpurd-getting-nextseek) Getting NExtSEEK

**The entirety of this section should be run as the** `apache` **user, unless otherwise specified.**

First, change into your home directory and clone the NExtSEEK git repository.

In our local installation of NExtSEEK, we've applied a paid theme called SmartAdmin that can be  Unzip the package into the subfolder `themes/SmartAdmin`.

Now, create a virtual environment to hold the Python packages that NExtSEEK uses to run.

## [hashtag](#page-iGwqsCLolxfAjNlhpurd-configuration) Configuration

**The entirety of this section should be run as the** `apache` **user, unless otherwise specified.**

### [hashtag](#page-iGwqsCLolxfAjNlhpurd-nextseek-configuration) NExtSEEK Configuration

You must configure NExtSEEK by changing the settings specified in `dmac/settings.py`. The following settings are the most important:

### [hashtag](#page-iGwqsCLolxfAjNlhpurd-gunicorn-configuration) Gunicorn Configuration

Change the settings in `gunicorn.conf.py`:

Once NExtSEEK has been properly configured, you'll need to go through some preliminary steps before starting the server. First, make sure that the directories you've set as `STATIC_ROOT` and `MEDIA_ROOT` exists. In this case, those will be `/var/www/nextseek/static` and `/var/www/nextseek/media`:

Have Django initialize the NExtSEEK database:

Now, have Django collect your static files to place them in the location you set in `STATIC_ROOT`, and have it generate a crontab for the cron jobs set in `dmac/settings.py`.

## [hashtag](#page-iGwqsCLolxfAjNlhpurd-running-the-nextseek-gunicorn-application-server) Running the NExtSEEK Gunicorn Application Server

**The entirety of this section should be run as the** `service-account` **user, or any user account with** `sudo` **access, unless otherwise specified.**

The Gunicorn server should be run as a `systemd` service with the following service file:

`/etc/systemd/system/nextseek.service`:

Create the file with those contents, then reload the `systemd` daemon so that it can see the new service file.

**Restart server**

**Stop server**

**Start server**

## [hashtag](#page-iGwqsCLolxfAjNlhpurd-apache-web-server) Apache Web Server

**The entirety of this section should be run as the** `service-account` **user, or any user account with** `sudo` **access, unless otherwise specified.**

Gunicorn does not serve static or media files; it only runs the Django app. Static / media files should be served by a production-grade web server, such as Nginx or Apache. The Apache web server has two functions: redirecting requests to your server's hostname to the internal Gunicorn server, and serving the static files stored in the `STATIC_ROOT` directory you set in `dmac/settings.py`.

Create the file `/etc/httpd/conf.d/nextseek.conf` with the following contents:

This configuration file is made for serving over HTTP. To serve the site with SSL encryption over HTTPS, the easiest method is to use Certbot. Install Certbot by following the instructions on the .

Once you've installed Certbot, run the following to have it create a certificate for the SEEK website. Answer the queries to the best of your abilities.

Certbot will automatically create the httpd configuration file for serving SEEK over HTTPS. Now, you can enable and start the httpd server, then open the firewall to accept HTTP and HTTPS connections.

**Restart server**

**Stop server**

**Start server**

Once the server has been started, visit https://your\_domain/ and NExtSEEK should be available.

