import numpy as np
from io import StringIO
from collections import OrderedDict
from itertools import chain
from .misc import __prog__


__all__ = ['Cell', 'read_energy', 'read_ewald', 'read_pot', 'read_volume',
           'read_epsilon', 'read_eigval', 'read_evbm', 'read_evbm_from_ne', 
           'read_dos']


class Cell():
    __slots__ = ['basis', 'sites', 'atoms', 'labels',
                 'atom_type', 'atom_num', 'atom_pot']
    def __init__(self, poscar=None, ptype='vasp'):
        '''
        A pythonic POSCAR class.
          - basis: basis vectors, (3,3) Float-List
          - sites: atomic positions in fractional coordinates
          - atoms: atomic symbols corresponding to sites
          - labels: atomic symbol+number
          - atom_pot: electrostatic potential at atomic sites
          - atom_type: unique atomic symbols
          - atom_num: the number of each type of atom
        
        '''
        for key in self.__slots__:
            setattr(self, key, None)        
        if poscar is not None:
            self.read(poscar, ptype=ptype)
    
    def read(self, poscar='POSCAR', ptype='vasp'):
        '''
        Parse POSCAR manually.
        
        '''
        with open(poscar, 'r') as f:
            lines = f.readlines()
        scale = float(lines[1].rstrip())
        basis = [[float(i) for i in line.strip().split()] 
                  for line in lines[2:5]]
        atom_type = lines[5].strip().split()
        atom_num = [int(i) for i in lines[6].strip().split()]
        sites = [[float(i) for i in line.strip().split()[:3]]
                 for line in lines[8:8+sum(atom_num)]]
        
        if scale < 0:
            # volume mode
            # scale factor is refined for later use
            scale = (-1)*np.cbrt(scale/np.linalg.det(basis))
            basis = scale * basis
        else:
            basis = scale * np.array(basis)
            
        postype = lines[7].strip()[0]
        if postype in 'sS':
            # selective dynamics mode
            err_info = 'POSCAR with selective dynamics mode is not supported'
            raise NotImplementedError(err_info)
        elif postype in 'cCkK':
            # the cartesian mode, convert to direct mode
            # basis has been scaled above
            sites = np.array(sites) @ np.linalg.inv(basis)
        else:
            # direct, fractional coordinates. Do nothing
            pass
        
        self.basis = basis
        self.atom_type = atom_type
        self.atom_num = atom_num
        self.sites = sites
        self.uniquepos()


    def uniquepos(self):
        '''
        Unique position order in POSCAR
        '''

        atoms = self.atom_type
        number = self.atom_num
        sites = self.sites

        atoms_uni = OrderedDict()
        for elmt in atoms:
            if elmt not in atoms_uni:
                atoms_uni[elmt] = []

        pidx = 0
        for num, atom in zip(number, atoms):
            for _ in range(num):
                atoms_uni[atom].append(pidx)
                pidx += 1
        atoms2 = list(atoms_uni.keys())
        number2 = list(map(len, atoms_uni.values()))
        posidx = list(chain(*atoms_uni.values()))

        self.atom_type = atoms2
        self.atom_num = number2
        self.sites = [sites[i] for i in posidx]

        # renew label
        self.atoms = []
        self.labels = []
        for num, symbol in zip(number2, atoms2):
            for idx in range(1, num + 1):
                self.atoms.append(symbol)
                self.labels.append(symbol + str(idx))

    def replace(self, atom1, atom2):
        '''
        Replace atom1 by atom2
        '''
        atom_type = self.atom_type
        atom_num = self.atom_num
        if atom1 not in atom_type:
            raise RuntimeError('Failed to locate {}'.format(atom1))
        else:
            idx = atom_type.index(atom1)
        
        # Alter atom_type & _num list
        if atom_num[idx] == 1:
            atom_type[idx] = atom2
        else:
            atom_num[idx] -= 1
            atom_num.insert(idx, 1)
            atom_type.insert(idx, atom2)
        self.atom_type = atom_type
        self.atom_num = atom_num
        
        # Refine POSCAR
        self.uniquepos()

    def write(self, poscar='POSCAR.new', ptype='vasp'):
        '''
        Write into POSCAR.

        '''
        lines = []
        lines.append('POSCAR generated by {}\n'.format(__prog__))
        lines.append('{:8.3f}\n'.format(1.0))
        for basis_i in self.basis:
            line = []
            for basis_ii in basis_i:
                line.append('{:22.16f}'.format(basis_ii))
            line.append('\n')
            lines.append(''.join(line))
        line = []
        for atom_i in self.atom_type:
            line.append('{:>5s}'.format(atom_i))
        line.append('\n')
        lines.append(''.join(line))
        line = []
        for num_i in self.atom_num:
            line.append('{:5d}'.format(num_i))
        line.append('\n')
        lines.append(''.join(line))
        lines.append('Direct\n')
        for pos_i, label_i in zip(self.sites, self.labels):
            line = []
            for pos_ii in pos_i:
                line.append('{:22.16f}'.format(pos_ii))
            line.append('{:>7s}\n'.format(label_i))
            lines.append(''.join(line))
        with open(poscar, 'w') as f:
            f.writelines(lines)

    def get_volume(self):
        basis = np.array(self.basis)
        return np.linalg.det(basis)

    def move(self, index, dr=(0,0,0)):
        '''
        Move atom

        Parameters
        ----------
        index : int
            The index of atom to be moved (index start from 0)
        dr : list or tuple
            Cartesian displacement of atom in Angstrom
        '''
        basis = np.array(self.basis)
        site = np.array(self.sites)
        pos = site @ basis
        pos[index] += np.array(dr)
        siten = pos @ np.linalg.inv(basis)
        site_i = siten[index]
        site_i -= np.floor(site_i)  # re-range to [0,1)
        self.sites[index] = [xi for xi in site_i]

    def diff(self, ncell, showdetail=False, showdiff=False,
             method=0, out='diff'):
        '''
        Compare to another Cell() object

        Parameters
        ----------
        ncell : Cell
            Another Cell() objcet, which nust has the same basis vectors.
        showdetail : bool, optional
            Whether detail information is displayed. The default is False.
        showdiff : bool, optional
            Whether differential information is displayed. The default is False.
        out : str, optional
            What return. Value is one of the following:
              - diff : differential sites (default), and ruturn None
              - far  : the indexes of farthest site pair and the distance

        '''
        basis = np.array(self.basis)
        site1 = np.array(self.sites)
        site2 = np.array(ncell.sites)
        site1[np.abs(site1-1) < 1E-2] = 0
        site2[np.abs(site2-1) < 1E-2] = 0
        pos1 = site1 @ basis
        pos2 = site2 @ basis
        idx1 = list(range(len(pos1)))  # sites indexes for pos1, and pos2
        idx2 = list(range(len(pos2)))
        state = []  # '', 's', 'i', 'v': normal, substitute, insert, vacancy
        idxn = []   # new index for cell2
        idxu = []   # perfect matched site index
        for i,pos in zip(idx1,pos1):
            dd = np.linalg.norm(pos2 - pos, axis=-1)
            index = np.argmin(dd)
            if dd[index] < 0.5:    # 0.5 Angstrom
                idx2.remove(index)
                idxn.append(index)
                if self.atoms[i] == ncell.atoms[index]:
                    state.append('')  # equivalent
                    idxu.append(i)    # matched-sites
                else:
                    state.append('s')   # substitution
            else:
                idxn.append(len(pos2))
                state.append('v')  # mismatch sites, i.e. vac.
                
        siten = []   # sites which are not in pos1, i.e. insertions
        n_insert = len(idx2)
        for index in idx2:
            idx1.append(len(idx1))    # create the new index
            siten.append(site2[index].tolist())
            idx2.remove(index)
            idxn.append(index)
            state.append('i')
        
        # all information
        site_all = self.sites + siten   # used atoms
        atom_all_1 = self.labels + ['vac', ]* n_insert # new labels    
        atom_all_2 = [(ncell.labels + ['vac', ])[i] for i in idxn]
        
        # diffarencal information
        diff_idx = [i for i in range(len(state)) if state[i]] # index
        diff_info = [state[i] for i in diff_idx]   # state
        diff_site = [site_all[i] for i in diff_idx]   # site
        diff_atom = [(atom_all_1[i],atom_all_2[i]) for i in diff_idx] # label
        
        # Analyze the farthest distance
        c1, c2, c3 = np.mgrid[-1:2,-1:2,-1:2]
        cc = np.c_[c1.flatten(),c2.flatten(),c3.flatten()]
        cc = np.expand_dims(cc, axis=1)  # shape: (27,1,3)
        dpos = np.array(diff_site+cc) @ basis  # defect pos, (27, P, 3)
        
        dist = []
        pos_all = np.array(site_all) @ basis
        for i, pos in enumerate(pos_all):
            if i in idxu:
                dd = np.linalg.norm(pos - dpos, axis=-1)  # (27,P)
                dmin = dd.min(axis=0)   # (P,)
                if int(method) == 1:
                    dx = dmin.mean()
                elif int(method) == 2:
                    dx = np.sqrt(np.square(dx).mean())
                else:
                    dx = dmin.min()
            else:
                dx = 0
            dist.append(dx)
        i = np.argmax(np.array(dist))
        index1, index2 = idx1[i], idxn[i]
        dist_max = dist[i]
        
        # display information
        dsp_head = '{:^7s}{:^8}{:^8}{:^8}{:^12s}{:^12s}'
        head = dsp_head.format('No.','f_a', 'f_b', 'f_c', 'previous', 'present')
        dsp = '{:^3s}{:<4d}{:>8.4f}{:>8.4f}{:>8.4f}{:^12s}{:^12s}'
        if showdetail:
            headi = head+'{:^12s}'.format('d_min')
            dspi = dsp+'{:^12.2f}'
            print(headi)
            info = zip(state, site_all, atom_all_1, atom_all_2, dist)
            for i, (s, p, b1, b2, d) in enumerate(info):
                if s is None: s=' '
                print(dspi.format(s, i+1, *p, b1, b2, d))
        if showdiff:
            if showdetail:
                print('diff: ')
            print(head)
            info = zip(diff_idx, diff_info, diff_site, diff_atom)
            for i, s, p, b in info:
                print(dsp.format(s, i+1, *p, *b))
        
        if out.lower().startswith('far'):
            return index1, index2, dist_max
        elif out.lower().startswith('diff'):
            return diff_info, diff_atom, diff_site
        else:
            return None


def read_energy(outcar='OUTCAR'):
    '''
    Read final energy from OUTCAR.

    '''
    with open(outcar, 'r') as f:
        data = f.readlines()
        for line in reversed(data):
            if 'sigma' in line:
                energy = float(line.rstrip().split()[-1])
                break
    return energy


def read_ewald(outcar='OUTCAR'):
    '''
    Read final Ewald from OUTCAR.

    '''
    with open(outcar, 'r') as f:
        data = f.readlines()
        for line in reversed(data):
            if 'Ewald energy   TEWEN' in line:
                ewald = float(line.rstrip().split('=')[-1])
                break
    return abs(ewald)


def read_pot(outcar='OUTCAR'):
    '''
    Read final site electrostatic potentials from OUTCAR.

    '''
    with open(outcar, 'r') as f:
        data = f.readlines()
        for idx, line in enumerate(reversed(data)):
            if 'electrostatic' in line:
                break 
    pot = []
    for line in data[2-idx:]:
        line = line.rstrip()
        if len(line) > 0:
            while len(line) > 0:
                pot.append(float(line[8:17]))
                line = line[17:]
        else:
            break 
    return pot


def read_volume(outcar='OUTCAR'):

    '''
    Read volume in A^3 from OUTCAR file
    '''
    with open(outcar, 'r') as f:
        data = f.readlines()
        for line in reversed(data):
            if 'volume' in line:
                break
    volume = float(line.strip().split()[-1])
    return volume


def read_epsilon(outcar='OUTCAR', isNumeric=False):
    '''
    Read the static dielectric properties from OUTCAR

    Returns
    -------
    Category, tensor, average

    '''
    target = 'STATIC DIELECTRIC'
    datalines = []
    with open(outcar, 'r') as f:
        line = f.readline()
        while line:
            if target in line:
                values = []
                if isNumeric:
                    f.readline()
                    for _ in range(3):
                        iline = f.readline()
                        value = iline.strip().split()
                        values.append(list(map(float, value)))
                else:
                    for _ in range(6):
                        values.append(f.readline().strip())
                datalines.append((line.strip(), values))
            line = f.readline()
    return datalines
    

def read_eigval(eigenval='EIGENVAL'):
    '''
    Read EIGENVAL file

    Parameters
    ----------
    eigenval : str, optional
        Filename of EIGENVAL. The default is 'EIGENVAL'.

    Returns
    -------
    (ele_num, kpt_num, eig_num), (kpts, kptw), (energy, weight)
    *_num: scalar
    kpts: (Nkpt,3)
    kptw: (Nkpt,)
    energy & weight: (Nbd, Nkpt)

    '''
    with open(eigenval, 'r') as f:
        data = f.readlines()
    ele_num, kpt_num, eig_num = map(int, data[5].rstrip().split())
    kptdata = np.loadtxt(StringIO(''.join(data[7::eig_num+2])))
    kpts = kptdata[:,:3]  # shape of (Nkpt,3)
    kptw = kptdata[:,3]  # shape of (Nkpt,)
    energy = []   # shape of (Nbd, Nkpt)
    weight = []   # shape of (Nbd, Nkpt)
    for i in range(eig_num):
        ei,wi = np.loadtxt(StringIO(
            ''.join(data[8+i::eig_num+2])),
            usecols=(1, 2), unpack=True)
        energy.append(ei)
        weight.append(wi)
    energy = np.vstack(energy)
    weight = np.vstack(weight)
    return (ele_num, kpt_num, eig_num), (kpts, kptw), (energy, weight)


def read_evbm(eigenval='EIGENVAL', pvalue=0.1):
    '''
    Read VBM & CBM energy and corresponding k-points. Threshold value to 
    determine unoccupied bands is allowed to assigned manually(0.1 default).

    Parameters
    ----------
    eigenval : str, optional
        Filename of EIGENVAL. The default is 'EIGENVAL'.
    pvalue : TYPE, optional
        Threshold value. The default is 0.1.

    Returns
    -------
    (e_vbm, index, k_vbm), (e_cbm, index, k_cbm), Egap

    '''
    with open(eigenval, 'r') as f:
        data = f.readlines()
    *_, kpt_num, eig_num = map(int, data[5].rstrip().split())
    kpts = np.loadtxt(StringIO(''.join(data[7::eig_num+2])))
    kpts[np.abs(kpts) < 1E-8] = 0
    energy = []
    weight = []
    wx = 1
    for i in range(eig_num):
        ei,wi = np.loadtxt(StringIO(
            ''.join(data[8+i::eig_num+2])),
            usecols=(1, 2), unpack=True)
        energy.append(ei)
        weight.append(wi)
        if wi.max() < pvalue and wx > (1-pvalue):
            break
        else:
            wx = wi.min()
    idxc = np.argmin(energy[-1])
    idxv = np.argmax(energy[-2])
    e_cbm = energy[-1][idxc]
    k_cbm = kpts[idxc]
    e_vbm = energy[-2][idxv]
    k_vbm = kpts[idxv]
    return (e_vbm, i-1, k_vbm[:3]), (e_cbm, i, k_cbm[:3]), e_cbm-e_vbm


def read_evbm_from_ne(eigenval='EIGENVAL', Ne=None, dNe=0):
    '''
    Read VBM & CBM energy from the number of electrons.

    Parameters
    ----------
    eigenval : str, optional
        Filename of EIGENVAL. The default is 'EIGENVAL'.
    Ne : TYPE, optional
        The number of electron. If None(default), read from EIGENVAL file.
    dNe : int, optional
        Additional adjustments of Ne.

    Returns
    -------
    (e_vbm, index, k_vbm), (e_cbm, index, k_cbm), Egap

    '''
    with open(eigenval, 'r') as f:
        data = f.readlines()
    e_num, kpt_num, eig_num = map(int, data[5].rstrip().split())
    
    if Ne is None:
        idxv = int((e_num + dNe)/2)  # start from 1
    else:
        idxv = int((Ne + dNe)/2)   # start from 1
    idxv, idxc = idxv-1, idxv      # start from 0
    
    e_vbms = np.loadtxt(StringIO(''.join(data[8+idxv::eig_num+2])))
    e_cbms = np.loadtxt(StringIO(''.join(data[8+idxc::eig_num+2])))
    idxvk = np.argmax(e_vbms, axis=0)[1]
    idxck = np.argmin(e_cbms, axis=0)[1]
    
    k_vbm = np.loadtxt(StringIO(data[7+idxvk*(eig_num+2)]))
    k_cbm = np.loadtxt(StringIO(data[7+idxck*(eig_num+2)]))
    
    e_vbm = e_vbms[idxvk,1]
    e_cbm = e_cbms[idxck,1]
    return (e_vbm, idxv+1, k_vbm[:3]), (e_cbm, idxc+1, k_cbm[:3]), e_cbm-e_vbm
    

def read_dos(doscar='DOSCAR', efermi=0):
    '''
    Read DOS data from DOSCAR or tdos.dat
    
    Returns
    energy, dos
    '''
    with open(doscar, 'r') as f:
        data = f.readlines()

    # Auto detect DOSCAR of tdos.dat
    num_i = [len(line.strip().split()) for line in data[:6]]
    ck = [num_i[0] == 4, num_i[2] == 1, num_i[3] == 1]
    isDOSCAR = True if all(ck) else False

    if isDOSCAR:
        NEDOS = int(data[5].strip().split()[2])
        data_select = data[6:6+NEDOS]
    else:
        data_select = data

    energy, dos = _read_dos(data_select, efermi)
    return energy, dos


def _read_dos(data, fermi=0):
    '''
    Read dos from text list
    '''
    energy = []
    dos = []
    for line in data:
        if not line.startswith('#'):
            data = [float(item) for item in line.strip().split()]
            energy.append(data[0]-fermi)
            dos.append(data[1])
    return energy, dos
