#!/bin/sh

# OpenSSL implementations do not consistently return a failing exit status
# for ``x509 -checkhost`` mismatches. Match its affirmative output instead so
# "does NOT match" can never be mistaken for success.
certificate_covers_host() {
    if [ "$#" -ne 2 ]; then
        return 2
    fi

    openssl x509 -in "$1" -noout -checkhost "$2" 2>/dev/null \
        | grep -Fq "does match certificate"
}
