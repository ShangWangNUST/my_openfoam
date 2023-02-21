#!/usr/bin/env python3

import re, argparse
from collections import namedtuple
import numpy as np
import matplotlib.pyplot as plt
from scipy import interpolate

Range = namedtuple('Range', 'min, max')
str2range = lambda s: Range._make(map(float, s.split(',')))
str2words = lambda s: s.split(',')

parser = argparse.ArgumentParser(description='Script for parsing txt files generated by ThermoCalc')
parser.add_argument('txtfile', type=str, help='source file')
parser.add_argument('-T', type=str2range, default='1600,1800', help='delimited list of temperature gradients')
parser.add_argument('-T0', type=float, default=None, help='temperature point of interest')
parser.add_argument('-b', '--base', type=str, default='Fe', help='base component')
parser.add_argument('-s', '--size', type=float, default=4, help='figure size')
parser.add_argument('-t', '--tail', type=float, default=0.5, help='part of temperature range outside the solidification interval')
parser.add_argument('-p', '--phases', action='store_true', help='plot phase fractions')
parser.add_argument('-m', '--manual', action='store_true', help='use manual temperature interval')
parser.add_argument('-v', '--verbose', action='store_true', help='increase output verbosity')
parser.add_argument('--pdf', action='store_true', help='save PDF file instead')
parser.add_argument('--skip-phases', type=str2words, default='', help='skip the comma-separated list of phases')
args = parser.parse_args()

class Regex:
    temperature = re.compile(r'Temperature \[(.*)\]')
    masspct = re.compile(r'Mass percent of (\w+) in ([\w#]+)')
    gram = re.compile(r'Amount of (\w+) in ([\w#]+) \[g\]')
    phase_mol = re.compile(r'Amount of ([\w#]+) \[mol\]')

def parse_element_content(c):
    if res := Regex.masspct.findall(c):
        return res[0]
    if res := Regex.gram.findall(c):
        return res[0]
    return None

def parse_phase_fraction(c):
    if res := Regex.phase_mol.findall(c):
        return res[0]
    return None

with open(args.txtfile, 'r') as f:
    line = f.readline()
    columns = line.strip().split('\t')

### 1. Read and sort the data
data = np.genfromtxt(args.txtfile, delimiter='\t', skip_header=1, filling_values=np.nan)
T = data[:,0]
# ThermoCalc generates several lines with the same temperature when some phase vanished.
# We choose those with zeros nad remove those without value, i.e. NaN
_, ind, inv, cnt = np.unique(T, return_index=True, return_inverse=True, return_counts=True)
for i in np.where(cnt > 1)[0]:
    j = np.argmax(np.count_nonzero(~np.isnan(data[ind[i]:ind[i]+cnt[i],:]), axis=1))
    ind[i] += j
data = data[ind]
T = data[:,0]

### 2. Analyze phase fractions
plot_phases = False
for i, c in enumerate(columns):
    if tunit := Regex.temperature.findall(c):
        if 'C' in tunit:
            T += 273.15
    if phase := parse_phase_fraction(c):
        if args.phases:
            plot_phases = True
        if phase == 'LIQUID':
            sol = T[np.argwhere(np.isnan(data[:,i]) == True)[-1][0]]
            liq = T[np.argwhere(data[:,i] == 1)[0][0]]
            deltaT = liq - sol
            print(f'Solidus = {sol} K, liquidus = {liq} K, deltaT = {deltaT:.3g}')
            if not args.manual:
                args.T = Range(sol - deltaT*args.tail, liq + deltaT*args.tail)
                if not args.T0:
                    args.T0 = liq - deltaT/1e10
if not args.T0:
    args.T0 = (args.T.min + args.T.max)/2
print(f'Tmin = {args.T.min:.6g}, T0 = {args.T0:.6g}, Tmax = {args.T.max:.6g}')

### 3. Filter the data
data = data[(T > args.T.min) & (T < args.T.max)]
T = data[:,0]

### 4. Extract phases and elements
elements, phases = [], []
for i, c in enumerate(columns):
    if res := parse_element_content(c):
        elem, phase = res
        if not elem in elements:
            elements.append(elem)
        if not phase in phases and not phase in args.skip_phases:
            if np.count_nonzero(~np.isnan(data[:,i])):
                phases.append(phase)
elements.remove(args.base)

print('Elements:', elements)
print('Phases:', phases)

### 5. Compute normalization factors
sums = { phase: np.zeros_like(T) for phase in phases }
for i, c in enumerate(columns):
    if res := parse_element_content(c):
        elem, phase = res
        if phase in phases:
            sums[phase] += data[:,i]

### 6. Generate subplots
Nfigs = len(elements) + (1 if plot_phases else 0)
Ncols = (Nfigs+1)//2
fig, axs = plt.subplots(ncols=Ncols, nrows=2, figsize=args.size*np.array((Ncols, 2)))
axis = lambda n: axs[n//Ncols, n%Ncols]
if Nfigs%2:
    fig.delaxes(axis(Nfigs))

### 7. Plot phase diagrams and find slopes
dashed = { 'linestyle': '--', 'linewidth': 0.5, 'color': 'k' }
C = { p: {} for p in phases }
slopes = { p: {} for p in phases }
for i, c in enumerate(columns):
    if plot_phases and (phase := parse_phase_fraction(c)):
        if phase in phases:
            axis(0).plot(T, data[:,i], label=f'{phase}')

    if res := parse_element_content(c):
        elem, phase = res
        if elem == args.base or not phase in phases:
            continue
        Y = data[:,i]
        # NB: zero values of sums[phase] are filtered out
        mask = sums[phase] > 0
        if np.count_nonzero(mask) > 0:
            X, Y = T[mask], Y[mask]/sums[phase][mask]
            spl = interpolate.UnivariateSpline(X, Y, k=1, s=0)
            slope = 1/spl.derivative()(args.T0)
            slopes[phase][elem] = slope
            C[phase][elem] = spl(args.T0)
            print(f'{elem:2s} {phase}: C(T0) = {spl(args.T0):.4g}, path slope = {slope:.4g}')

            n = elements.index(elem) + (1 if plot_phases else 0)
            axis(n).plot(X, Y, label=f'{phase} ({slope:.4g} K)')
            if not np.isnan(slope):
                f = lambda T: spl(args.T0) + (T-args.T0)/slope
                axis(n).plot(X, f(X), **dashed)

for n, elem in enumerate(elements):
    n += 1 if plot_phases else 0
    axis(n).axvline(x=args.T0, **dashed)
    axis(n).set_title(elem)
    axis(n).legend()

if plot_phases:
    [ axis(0).axhline(y=y, **dashed) for y in range(2) ]
    axis(0).set_title('Phase fractions')
    axis(0).legend()

composition = f'{args.base}-' + '-'.join([ f'{elem}{100*C:.3g}' for elem, C in C['LIQUID'].items() ])
fig.suptitle(composition, fontweight="bold")

### 8. Calculate a single-phase freezing range
for phase in phases:
    if phase == 'LIQUID':
        continue
    sumL, sumS = 0, 0
    for elem in elements:
        mL, mS = slopes['LIQUID'][elem], slopes[phase][elem]
        CL, CS = C['LIQUID'][elem], C[phase][elem]
        sumL += (CS - CL)/mL
        sumS += (CS - CL)/mS
    DeltaT1, DeltaT2 = 0, 0
    for elem in elements:
        mL, mS = slopes['LIQUID'][elem], slopes[phase][elem]
        CL, CS = C['LIQUID'][elem], C[phase][elem]
        dT1, dT2 = (CS - CL)**2/sumS, CL*(CS - CL)*(1/sumL - 1/sumS)
        DeltaT1 += dT1; DeltaT2 += dT2
        if args.verbose:
            print(f' -- {elem:2s}: slopeS = {(CS - CL)/sumS:.4g}, slopeL = {(CS - CL)/sumL:.4g}, ' +
                f'dT1 = {dT1:.3g}, dT2 = {dT2:.3g}, K = {CS/CL:.4g}, ' +
                f'mL/mS = {mL/mS:.4g}, mL*(K-1)*C0 = {(CS-CL)*mL:.4g}')
    print(f'{phase}: K={sumL/sumS:.2f}, DeltaT1 = {DeltaT1:.3g}, DeltaT2 = {DeltaT2:.3g}')


### 9. Estimate the fcc-bcc ratio according to the Schaeffer--DeLong diagram
if args.base == 'Fe':
    Ni_coeffs = { 'Ni': 1, 'Mn': 0.5, 'C': 30, 'N': 30 }
    Cr_coeffs = { 'Cr': 1, 'Mo': 1.5, 'Si': 1.5, 'Nb': 0.5 }
    Ni_eq = Cr_eq = 0
    for elem, C in C['LIQUID'].items():
        if elem in Ni_coeffs:
            Ni_eq += C*Ni_coeffs[elem]
        if elem in Cr_coeffs:
            Cr_eq += C*Cr_coeffs[elem]
    a, b = 7, 10
    bcc_dist = lambda x, y: (14 + b/a*(x - 19) - y)*a/np.sqrt(a**2 + b**2)
    ten_pct_dist = bcc_dist(21, 12)
    bcc_wt = 10/ten_pct_dist*bcc_dist(Cr_eq*100, Ni_eq*100)
    print(f'Ni_eq = {Ni_eq:.3f}, Cr_eq = {Cr_eq:.3f}, %bcc = {bcc_wt:.2f}')

fig.tight_layout()
if args.pdf:
    plt.savefig(f'{composition}.pdf')
else:
    plt.show()
