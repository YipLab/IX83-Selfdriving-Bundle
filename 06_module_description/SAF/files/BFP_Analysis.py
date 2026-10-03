import cv2
import glob
import json
import numpy as np
import os
import tifffile as tf
import matplotlib.pyplot as plt

def findCircle(im, r_buff = 30, show = False ,maxint = None):
	# Find circle in image
	# Input:im > image (2D np array)
	#		r_buff > radius buffer (int in px)
	#		show > show image with circle (boolean) 
	# Output: Tuple (center, radius) of circle

	#Apply guassian blur
	#im = cv2.GaussianBlur(im, (3,3), 0)
	#Convert to 8-bit for Circle detection
	im8 = im*255./np.amax(im)
	if maxint == None:
		im8 = im8.astype(np.uint8)
	else:
		im8 = im*255./maxint
		im8[im8 > 255] = 255
		im8 = im8.astype(np.uint8)
	
	#Hough Circle algorithm for circle detection
	circles = cv2.HoughCircles(im8, cv2.HOUGH_GRADIENT, 1, 200, param1 = 50, param2 = 50, minRadius=100)
	circles = np.uint16(np.around(circles))
	circle = circles[0,0]
	center = [circle[1], circle[0]]
	r = circle[2]+r_buff

	#Show image circle (optional)
	if show:
		#cv2.circle(im, (center[1], center[0]), r-r_buff, 0, thickness = 5)
		cv2.circle(im, (center[1], center[0]), r, 0, thickness = 5)
		tf.imshow(im, cmap='gray')

	return (center, r)

def getRadialprofile(im, c = None, r = None, prof_len = 1000, show = False):
	#Find the radial profile of an image
	#Input:	im > image (2D np array)
	#		c and r > from findCircle()
	#		prof_len > profile length (should be longer than 1000)

	#If no center or radius is give, find c and r
	if c == None or r == None:
		c,r = findCircle(im)

	#Initialize radialprofiles
	radialprofiles = np.zeros(prof_len)
	
	#Crop circle
	im_crop = im[c[0]-r:c[0]+r+1,c[1]-r:c[1]+r+1]
	y, x = np.indices((im_crop.shape))
	rs = np.sqrt((x - r)**2 + (y - r)**2)
	rs = rs.astype(np.int)

	tbin = np.bincount(rs.ravel(), im_crop.ravel())
	nr = np.bincount(rs.ravel())
	radialprofile = tbin / nr
	radialprofiles[:len(radialprofile)] = radialprofile

	if show: 
		plt.plot(radialprofiles)

	return radialprofiles

def getRadialprofiles(folder, circle, r_buff = 30, prof_len = 1000, show = False):
	#Find the radial profiles of a BFP over time (multiple single images)
	file_names = sorted(glob.glob(folder + '*.tif')) #sort by name
	with open(folder + 'metadata.txt') as json_file:
		data = json.load(json_file)
	
	#Initialize outputs
	timeseries = [] #To record time of acqusition in ms
	radialprofiles = np.zeros([len(file_names), prof_len])

	im = tf.imread(file_names[circle])
	c, r = findCircle(im, r_buff = r_buff, show = show)
	
	for i in range(len(file_names)):
		timeseries.append(data['FrameKey-' + str(i) + '-0-0']['ElapsedTime-ms'])
		radialprofiles[i, :] = getRadialprofile(tf.imread(file_names[i]), c = c, r = r, prof_len = prof_len, show = show)

	return (timeseries, radialprofiles)

def getRadialprofiles2(file, circle, r_buff = 30, prof_len = 1000, show = False):
	#Find the radial profiles of a BFP over time (single stack)
	im = tf.imread(file)
	c, r = findCircle(im[circle,:,:], r_buff = r_buff, show = show)

	#Initialize outputs
	radialprofiles = np.zeros([im.shape[0], prof_len])
	
	for i in range(im.shape[0]):
		radialprofiles[i, :] = getRadialprofile(im[i,:,:], c = c, r = r, prof_len = prof_len, show = show)

	return radialprofiles

def getCircumprofile(im, c = None, r = None, r_buff = 30, m = 10, show = False, save = False, name = None):
    #Find circumferential profile
    #Input:	im > image (2D np array)
    #		c and r > from findCircle()
    #		r_range > average between r-r_range to r
    #		prof_len > profile length (should be longer than 1000)

    #If no center or radius is give, find c and r
    if c == None or r == None:
    	c,r = findCircle(im, r_buff = 30)

    #Crop circle
    im_crop = im[c[0]-r:c[0]+r+1,c[1]-r:c[1]+r+1]

    y, x = np.indices((im_crop.shape))

    ths = (np.arctan2(y - r,x - r) + np.pi) * 10
    ths = ths.astype(np.int)

    rs = np.sqrt((x - r)**2 + (y - r)**2)
    rs = rs.astype(np.int)

    circprofile = []

    for t in np.unique(ths):
        mask = (rs > r-r_buff-m) * (rs < r-r_buff+m) * (ths == t)
        #circprofile.append(np.sum(im_crop*mask)/np.sum(mask))
        circprofile.append(np.max(im_crop*mask))

    '''if show: 
    	plt.plot(circprofile)'''

    if save and name != None:
        tf.imsave(name, im_crop)    

    return circprofile

def getCircumprofiles(folder, circle, c= None, r = None, r_buff = 30, m= 10, show = False, save = False, maxint = None):
    file_names = sorted(glob.glob(folder + '*.tif')) #sort by name

    #Initialize outputs
    circprofiles = []

        #If no center or radius is give, find c and r
    if c == None or r == None:
	    im = tf.imread(file_names[circle])-70.
	    c, r = findCircle(im, r_buff = r_buff, show = show, maxint=maxint)
	    print(c, r)
    
    for i in range(len(file_names)):
        circprofiles.append(getCircumprofile(tf.imread(file_names[i]), c = c, r = r, m = m, show = show, save = save, name = file_names[i] + '_cropped'))

    return circprofiles