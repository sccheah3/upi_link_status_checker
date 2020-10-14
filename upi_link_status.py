#! /bin/python

"""
This program checks for the upi link status between multi-processor server systems. Confidential values have been removed.
"""


import subprocess
import sys
import re
import imp
import copy
import pprint


# might have to add extra entries for dmi's populated with 
#	"mbd-x11dpu-z+" or cases with "-p" at end
MB_SET_3_UPI = {
		'X11DPU-Z+', 'X11DPU-ZE+', 'X11DPH-TQ', 'X11DPH-T', 'X11DPX-T', 'X11DPH', 'X11DGQ', 'X11DSN-TSQ', 'X11DSN-TS', 'X11DSF-E', 'X11DSC+', 'X11DPT-BH', 'X11DPS-RE', 'X11DPG-SN', 'X11DPG-SN(T)', 'X11DPG-OT-CPU', 'X11DPG-HGX2', 'X11DGO-T', 
		'X11QPL', 'X11QPH+',
		'X11OPI-CPU', 'X11OPI', 'X11OPI1',
}

ACCEPTABLE_INIT_STATES = {'3', '7', 'B', 'F'}


def get_motherboard_pn():
	dmi_info = subprocess.Popen(['dmidecode', '-t' ,'baseboard'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

	match = re.search(r'\s*Product\s*Name\s*:[ \t]*([+\w\.-]+)', dmi_info.stdout.read(), re.IGNORECASE)
	
	if not match:
		return None

	return match.group(1)
	

# search for number of CPU sockets
def get_num_cpu_sockets():
	processor_info = subprocess.Popen(['dmidecode', '-t', 'processor'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

	match = re.findall(r'\s*Socket\s*Designation\s*:[ \t]*[\w\.]+', processor_info.stdout.read(), re.IGNORECASE)
	
	if not match:
		return None

	return len(match)

# returns a map {bus:[[device, register/value]]}, i.e. {d7:[[0f, 00002300], [0e, 00002301]]} w/ sorted values
def get_upi_links():
	upi_info = subprocess.Popen(['setpci', '-v', '-d', 'VENDOR_ID:DEVICE_ID', 'OFFSET_VAL'], stdout=subprocess.PIPE,
								stderr=subprocess.STDOUT)

	match = re.findall(r'\w+:(\w+):(\w+).\w+\s+@\w+\s+=\s+(\w+)', upi_info.stdout.read())

	if not match:
		#Try to see if it's actually an ice lake sku (which differs from SKX, CLX and Cooper)
		upi_info = subprocess.Popen(['setpci', '-v', '-d', 'VENDOR_ID:DEVICE_ID', 'OFFSET_VAL'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

		match = re.findall(r'\w+:(\w+):(\w+).\w+\s+@\w+\s+=\s+(\w+)', upi_info.stdout.read())

		if not match:
			return None

	upi_map = {}

	for m in match:
		bus = m[0]
		device = m[1]
		register = m[2]

		if bus in upi_map.keys():
			upi_map[bus].append([device, register])
		else:
			upi_map[bus] = [[device, register]]

	# fix ordering for upi links. 0th index will correspond to first upi link
	for reg in upi_map.values():
		reg.sort()

	return upi_map


# @links = 3D list [[[device, register]]]
# check bits 9:8 (init_state) of the link layer is INIT_DONE
# modifies @links to be [[[device, boolean]]]
def check_link_init_state(links):
	regout = copy.copy(links)
	
	for bus_registers in enumerate(regout):
		for reg in enumerate(bus_registers[1]):
			if regout[bus_registers[0]][reg[0]][1][-3] not in ACCEPTABLE_INIT_STATES:
				regout[bus_registers[0]][reg[0]][1] = False
			else:
				regout[bus_registers[0]][reg[0]][1] = True


# @links = 2D array of [device, boolean] values
# check the number of up upi links per cpus are the same
def is_up_link_count_identical(links):
	# count num of True
	count = sum([status[1] for status in links[0]])

	for link in links:
		if sum([status[1] for status in link]) != count:
			return False

	return True


# @upi_map = upi map of {bus:[device,[register/value]]}
# @num_upi_links = the actual number of upi links supported by the board
# @total_num_links = all links in respect to each CPU. i.e., 2 CPU, 3 UPI = 6 total UPI even though they share
def is_links_per_socket_valid(upi_map, num_upi_links, total_num_links):
	num_verified_links = 0

	for links in upi_map.values():
		count = 1
		for link in links:
			if count > num_upi_links:	# ignore links past supported links
				break

			num_verified_links += link[1]	# count links with status True
			count += 1

	return num_verified_links == total_num_links


# save result to log file
def save_result(result, upi_map, num_upi_links):
	global SYS_DIR
	with open("%s/upi_link_result.log" % str(SYS_DIR), "w") as outF:

		sorted_keys = sorted(upi_map.keys())

		header = ["CPU"]
		for i in range(num_upi_links):
			header.append("\tUPI" + str(i))

		try:
			if result:
				outF.write("Result: PASS\n\n")
			else:
				outF.write("Result: FAIL\n\n")
		except:
			print("ERROR: save_result, failed to write status to upi_link_result.log")

		header = "".join(header)
		try:
			outF.write(header + "\n")
			outF.write("----" * ((num_upi_links * 2) + 1) + "\n")
		except:
			print("ERROR: save_result, failed to write header to upi_link_result.log")

		rows = []
		for i in range(len(sorted_keys)):
			row = []
			row.append("CPU" + str(i))

			for j in range(num_upi_links):  # only iterate through
				status = upi_map[sorted_keys[i]][j]
				if status[1]:
					row.append("\tPASS")
				else:
					row.append("\tFAIL")

			rows.append(row)

		try:
			for row in rows:
				outF.write("".join(row) + "\n")
		except:
			print("ERROR: save_result, failed to write rows to upi_link_result.log")

	# outF.close()


# outputs result to console with coloring for PASS FAIL
def output_result(result, upi_map, num_upi_links):
	sorted_keys = sorted(upi_map.keys())

	header = ["CPU"]
	for i in range(num_upi_links):
		header.append("\tUPI" + str(i))

	print ""

	if result:
		print("Result: \033[1;32;40mPASS\n")
	else:
		print("Result: \033[1;31;40mFAIL\n")

	print("\033[0;37;40m"),

	header = "".join(header)
	print(header)
	print("----" * ((num_upi_links * 2) + 1))

	rows = []
	for i in range(len(sorted_keys)):
		row = []
		row.append("CPU" + str(i))

		for j in range(0, num_upi_links):  # only iterate through
			status = upi_map[sorted_keys[i]][j]
			if status[1]:
				row.append("\t\033[1;32;40mPASS")
			else:
				row.append("\t\033[1;31;40mFAIL")

			row.append("\033[0;37;40m")

		rows.append(row)

	for row in rows:
		print("".join(row))

	print ""


# saves error message into file, then sys.exit with respective error code
def save_error_and_exit(msg, error_code):
	global SYS_DIR
	with open("%s/upi_link_error.log" % str(SYS_DIR), "w") as outF:
		try:
			outF.write("Error: " + msg + "\n")
		except:
			print("ERROR: save_error_and_exit, failed to write error message to upi_link_error.log")

	print "\033[1;31;40mError: \033[0;37;40m" + msg
	sys.exit(error_code)


def get_sys_dir():
	with open('/root/stage2.conf') as iFD:
		for line in iFD.readlines():
			if line.startswith("SYS_DIR="):
				return line.split("=")[1].strip('\n"')

	return '/root'


def main():
	global SYS_DIR 
	SYS_DIR = get_sys_dir()

	if not SYS_DIR:
		SYS_DIR = '/root'

	mb_pn = get_motherboard_pn()
	if not mb_pn:
		save_error_and_exit("Motherboard part number not found in DMI.", 2)

	num_upi_links = 0
	mb_pn = mb_pn.upper().strip()
	if mb_pn in MB_SET_3_UPI:
		num_upi_links = 3
	else:
		num_upi_links = 2

	num_cpu_sockets = get_num_cpu_sockets()
	if not num_cpu_sockets:
		save_error_and_exit("Unable to verify number of CPU sockets.", 3)
	elif num_cpu_sockets < 2:
		save_error_and_exit("Motherboard does not have at least 2 sockets.", 4)

	upi_map = get_upi_links()
	if not upi_map:
		save_error_and_exit("Failed to get UPI links.", 5)

	# check if bits 9:8 is 0x3 for INIT_DONE state
	check_link_init_state(upi_map.values())

	if not is_up_link_count_identical(upi_map.values()):
		save_error_and_exit("Link count between CPUs is not identical.", 6)

	# case where MB with 2 UPI is accidentally put into 3 UPI set. Boards that support 2 UPI while 3 UPI links found will still run.
	num_found_links = len(upi_map.values()[0])
	if num_found_links < num_upi_links:
		save_error_and_exit("Found " + str(num_found_links) + " UPI links instead of " + str(num_upi_links) + ".", 7)

	result = is_links_per_socket_valid(upi_map, num_upi_links, num_upi_links*num_cpu_sockets)
	save_result(result, upi_map, num_upi_links)
	output_result(result, upi_map, num_upi_links)

	if not result:
		print "Failed. Check log file.\n"
		sys.exit(1)



if __name__ == '__main__':
	main()

