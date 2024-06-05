import os
import boto3

ec2 = boto3.client('ec2')
elbv2 = boto3.client('elbv2')


def lambda_handler(event, context):

    # ELB ARN
    # elb_arn = os.environ.get('elb_arn').strip()
    # Listener(s) ARN(s) to forward to Target Groups that are to be configured for weighted routing.
    # list_of_listeners = [item.strip() for item in os.environ.get('list_of_listeners').split(",")]

    # Read environment variables
    elb_arn = os.environ['elb_arn'].strip()
    list_of_listeners = [item.strip() for item in os.environ['list_of_listeners'].split(",")]

    """
    Environment Variables: Below two variables are required to run Lambda. Designed to pull from environment values. 
    This sample POC Lambda is written to address one ELB, if you have more than one ELB, either run multiple instances
    of the Lambda or modify Lambda code to loop through each ELB arn.  
    elb_arn = 'arn_value'
    list_of_listeners = 'arn_value'
    """

    # print ('elb_arn from Variable ', elb_arn)
    # print ('list of listners ', list_of_listeners)

    # Invoke Step 1:
    target_group_arn_list = find_target_groups(elb_arn)
    # print("Target Group arn List Before Step 2", json.dumps(target_group_arn_list))


    """
    One Target Group (TG) can be associated to more than one Listener. So, we first find the weights in terms of
    attached "healty" EC2 machines. So, it will avoid duplicating for each Listener. 
    Then update only those Listeners that are supplied as input parameter.
    """

    # Invoke Step 2:
    # Find total healthy EC2's vCPU count per each Target Group
    tg_arn_vcpu_weight_list = []
    total_weight = 0
    for tg_arn in target_group_arn_list:
        vcpu_weight = get_vcpu_count(tg_arn)
        total_weight += vcpu_weight
        tg_weight_dict = {'TargetGroupArn': tg_arn, 'Weight': vcpu_weight}
        tg_arn_vcpu_weight_list.append(tg_weight_dict)
    print('Absolute:  tg_arn_vcpu_weight_list', tg_arn_vcpu_weight_list)

    # Calculating weight units from 0 to 999 in ratios across TGs for a given listener.
    # total_weight = sum(item['Weight'] for item in tg_arn_vcpu_weight_list)

    if total_weight != 0:
        tg_arn_ratio_list = []
        for item in tg_arn_vcpu_weight_list:
            ratio = (item['Weight'] / total_weight) * 999
            tg_ratio_dict = {'TargetGroupArn': item['TargetGroupArn'], 'Weight': int(ratio)}
            tg_arn_ratio_list.append(tg_ratio_dict)
        print('Ratio:  tg_arn_ratio_list', tg_arn_ratio_list)

    """
    This funciton updates listner's weight distribution to TGs. Takes multiple Listeners as input and TGs weights
    """
    # Invoke Step 3:
    # list_of_listeners = ['arn1, arn2,...']
    # Target Groups and Weights list
    #modify_listener_targetgroup_weights(list_of_listeners, tg_arn_vcpu_weight_list)
    if total_weight != 0:
        modify_listener_targetgroup_weights(list_of_listeners, tg_arn_ratio_list)

    return "Function completed successfully"

# Step1: Find List of Target Groups for a given ELB's arn
def find_target_groups(elb_arn):

    try:
        # Fetch target groups for the given ELB ARN
        response = elbv2.describe_target_groups(LoadBalancerArn=elb_arn)
        # print(response)
        # retrieve target group ARNs
        target_group_arns = [tg['TargetGroupArn'] for tg in response['TargetGroups']]
    except Exception as e:
        # print("An error occurred:", e)
        return f"An error occurred: {e}"

    return target_group_arns


# Step 2: Find total healthy EC2's vCPU count per each Target Group
def get_vcpu_count(target_group_arn):
    # Returns the total vCPU count of all healthy EC2 instances registered with the given Target Group ARN.
    # create a boto3 client for EC2 and ELBV2 services

    # get the list of registered instances in the target group
    instances = elbv2.describe_target_health(TargetGroupArn=target_group_arn)['TargetHealthDescriptions']

    # get the instance IDs of all healthy instances
    healthy_instance_ids = [instance['Target']['Id'] for instance in instances if
                            instance['TargetHealth']['State'] == 'healthy']
    # print("healthy instances type", healthy_instance_ids)
    # print("healthy instances", json.dumps(healthy_instance_ids))

    # get the vCPU count for all healthy instances
    vcpu_count = 0
    for instance_id in healthy_instance_ids:
        instance = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
        print('describe_instances output', instance)
        vcpu_count += instance['CpuOptions']['CoreCount'] * instance['CpuOptions']['ThreadsPerCore']

    return vcpu_count

# Step 3: Working: Update ELB listener's target group weights, takes input of Listener ARN and Target Group and its weight dict.
# Modifies the weights of multiple target groups in a listener's forward configuration.
def modify_listener_targetgroup_weights(List_of_Listeners, target_group_weights):

    response = elbv2.describe_listeners(ListenerArns=List_of_Listeners)

    # print ("describe_listeners output of response = ", json.dumps(response))

    # Build target group ARNs and their corresponding weights
    target_groups = {}

    for tg in target_group_weights:
        target_groups[tg['TargetGroupArn']] = tg['Weight']

    # Loop through the listeners in response
    for listener in response['Listeners']:
        listener_arn = listener['ListenerArn']

        # Loop through the target groups for this listener
        # print ("Listener in the loop", listener_arn)
        total_weight = 0
        for tg in listener['DefaultActions'][0]['ForwardConfig']['TargetGroups']:
            tg_arn = tg['TargetGroupArn']
            # Update the weight if the target group is in Input1
            if tg_arn in target_groups:
                """
                999 is max value that can be given to target group's weight. Target Groups take values from 0 to 999
                If any of the TG's weight crosses 999, this logic sets it to 999, 
                so you may modify weight calculation logic to divide by a common factor to bring all TGs values 
                equitably so none goes beyond 999.
                """
                if target_groups[tg_arn] > 999:
                    tg['Weight'] = 999
                else:
                    tg['Weight'] = target_groups[tg_arn]

                total_weight += tg['Weight']

                # Quick test with random weights for associated TGs.
                # random_weight = random.randint(1, 999)
                # tg['Weight'] = random_weight
                # total_weight += random_weight

        # Call modify_listener to update the weights of the target groups
        # print ('total weight = ', total_weight, ' listener arn= ', listener_arn, ' Default actions = ', json.dumps(listener['DefaultActions']))
        # At least one of the TGs weight must be > 0
        if total_weight:
            elbv2.modify_listener(ListenerArn=listener_arn, DefaultActions=listener['DefaultActions'])
            print("update successful for listener_arn", listener_arn)
        else:
            print('update skipped for listener', listener_arn)


# For all forwarding rules update
def update_target_group_weights(elb_name, listener_port):
    elb_client = boto3.client('elbv2')
    target_groups_response = elb_client.describe_target_groups(LoadBalancerArn=elb_name)
    listener_response = elb_client.describe_listeners(LoadBalancerArn=elb_name, Port=listener_port)
    listener_arn = listener_response['Listeners'][0]['ListenerArn']
    rules_response = elb_client.describe_rules(ListenerArn=listener_arn)

    for rule in rules_response['Rules']:
        action = rule['Actions'][0]
        if action['Type'] == 'forward':
            target_group_arn = action['TargetGroupArn']
            target_group_weights = []
            targets_response = elb_client.describe_target_health(TargetGroupArn=target_group_arn)

            for target in targets_response['TargetHealthDescriptions']:
                target_group_weights.append({
                    'Id': target['Target']['Id'],
                    'Weight': target['Weight']
                })

            elb_client.set_target_group_weights(
                TargetGroupArn=target_group_arn,
                Targets=target_group_weights
            )