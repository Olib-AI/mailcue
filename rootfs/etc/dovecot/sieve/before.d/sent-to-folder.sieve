require ["fileinto", "mailbox", "envelope", "subaddress"];

# Automatically route sent email BCCs (recipient+sent@domain) into the Sent folder
if envelope :detail "to" "sent" {
    fileinto :create "Sent";
    stop;
}
