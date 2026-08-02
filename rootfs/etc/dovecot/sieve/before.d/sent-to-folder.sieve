require ["fileinto", "mailbox", "envelope", "subaddress", "imap4flags"];

# Automatically route sent email BCCs (recipient+sent@domain) into the Sent folder
if envelope :detail "to" "sent" {
    addflag "\\Seen";
    fileinto :create "Sent";
    stop;
}
