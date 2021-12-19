import boto3
from pino import pino
from dotenv import dotenv_values
import os
import time

def ping(addr):
    response = os.system("fping -c 1 -t 50 " + addr + " > /dev/null 2>&1")
    if response == 0:
        return True
    else:
        return False


config = dotenv_values(".env")


# Checking config
try:
    config["AWS_REGION"]
except KeyError:
    config["AWS_REGION"] = 'us-east-1'

ec2 = boto3.client('ec2', region_name=config["AWS_REGION"])

logger = pino(
    bindings={"app": "aws-opnsense-ha", "region": config["AWS_REGION"]}
)


def main():
    while True:

        logger.info("OPNSense HA Script Started")
        logger.info("Getting current firewall state")
        
        # Get main EIP current data
        eipData = ec2.describe_addresses(PublicIps=[config["MAIN_EIP"]])["Addresses"][0]
        eipMainEniId = eipData["NetworkInterfaceId"]
        eipMainAssoc = eipData["AssociationId"]
        eipMainAlloc = eipData["AllocationId"]

        # Get primary instance ID
        primInstanceId = eipData["InstanceId"]
        
        # Get current firewall data
        hostPubEniData = ec2.describe_network_interfaces(Filters=[
            {
                'Name': 'addresses.private-ip-address',
                'Values': [
                    config["HOST_PUB_NET_IP"],
                ]
            },
        ])["NetworkInterfaces"][0]
        hostPubEniId = hostPubEniData["NetworkInterfaceId"]
        hostInstanceId = hostPubEniData["Attachment"]["InstanceId"]

        hostPrivEniData = ec2.describe_network_interfaces(Filters=[
            {
                'Name': 'addresses.private-ip-address',
                'Values': [
                    config["HOST_PRIV_NET_IP"],
                ]
            },
        ])["NetworkInterfaces"][0]
        hostPrivEniId = hostPrivEniData["NetworkInterfaceId"]

        # Get general data
        vpcId = hostPrivEniData["VpcId"]

        # Get peer instance data
        peerPrivEniData = ec2.describe_network_interfaces(Filters=[
            {
                'Name': 'addresses.private-ip-address',
                'Values': [
                    config["PEER_PRIV_NET_IP"],
                ]
            },
        ])["NetworkInterfaces"][0]
        peerPrivEniId = peerPrivEniData["NetworkInterfaceId"]

        # Logging retrived data

        logger.info("Primary EIP ENI ID: " + eipMainEniId)
        logger.info("Primary EIP association ID: " + eipMainAssoc)
        logger.info("Primary EIP allocation ID: " + eipMainAlloc)
        logger.info("Primary EC2 ID: " + primInstanceId)

        logger.info("Current private ENI ID: " + hostPrivEniId)
        logger.info("Current public ENI ID: " + hostPubEniId)
        logger.info("Current EC2 ID: " + hostInstanceId)

        logger.info("Peer private ENI ID: " + peerPrivEniId)

        unit = ''   
        # Checking current unit
        if hostInstanceId == primInstanceId:
            unit = "Primary"
        else:
            unit = "Backup"        


        logger.info("This unit is " + unit)

        # Backup unit init
        if unit == "Backup":
            successChecks = 0
            logger.info("Checking connection to primary unit")
            while successChecks < 5:
                if ping(config["PEER_PRIV_NET_IP"]):
                    successChecks += 1
            logger.info("Connection to primary unit entablished")

            # Shutting down IPSec service on backup instance
            response = os.system("/usr/local/sbin/configctl ipsec stop > /dev/null 2>&1")
            if response == 0:
                logger.info("IPSec service stopped")
            else:
                logger.warn("Error while stopping IPSec service")

            # Starting healthcheck
            missedPing = 0
            while missedPing <= int(config["FAILOVER_TRIGGER_THRESHOLD"]):
                if not ping(config["PEER_PRIV_NET_IP"]):
                    missedPing += 1
                    logger.warn("Missed " + str(missedPing) + " responces from primary unit")
                else:
                    missedPing = 0
            
            # Initiate Failover
            logger.warn("Primary unit down, initiating failover")
            startTime = time.time()
            # Getting VPC routes table
            rts = ec2.describe_route_tables(Filters=[
                    {
                        'Name': 'vpc-id',
                        'Values': [
                            vpcId,
                        ]
                    },
                ],
            )["RouteTables"]

            # Switching routes
            for rt in rts:
                rtId = rt["RouteTableId"]
                for r in rt["Routes"]:
                    if "NetworkInterfaceId" in r.keys():
                        if r["NetworkInterfaceId"] == peerPrivEniId:
                            ec2.replace_route(
                                DestinationCidrBlock=r["DestinationCidrBlock"],
                                RouteTableId=rtId,
                                NetworkInterfaceId=hostPrivEniId
                            )
                            logger.info("Replaced route: " + r["DestinationCidrBlock"])
                        else:
                            logger.info("Skipping route, not pointing to an ENI")

                        

            # Switching EIP association
            res = ec2.associate_address(
                AllocationId=eipMainAlloc,
                NetworkInterfaceId=hostPubEniId,
                AllowReassociation=True,
            )

            if res["AssociationId"]:
                logger.info("EIP Reassociated")
                eipMainAssoc = res["AssociationId"]

            # Enabling IPSec service
            response = os.system("/usr/local/sbin/configctl ipsec start > /dev/null 2>&1")
            if response == 0:
                logger.info("IPSec service started")
            else:
                logger.error("Error while starting IPSec service")
            
            unit = "Primary"
            endTime = time.time()
            duration = int(endTime - startTime)
            logger.info("Failover ended in " + duration + " seconds")
            
        time.sleep(300)



if __name__ == '__main__':
    main()
