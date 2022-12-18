import os
import shutil
import numpy as np
from matplotlib import cm
from matplotlib import pyplot as plt
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import copy
import pandas as pd
from scipy import optimize

from geometry import Plane,Section
from aero import Case,avl_cmd

class AutoTail():
    def __init__(self,config_file:str): 
        path=os.path.abspath(os.getcwd())
        if os.path.isdir(path+"/results")==True:
            shutil.rmtree(path+"/results")
        if os.path.isdir(path+"/generated planes")==True:
            shutil.rmtree(path+"/generated planes")
        if os.path.isdir(path+"/cases")==True:
            shutil.rmtree(path+"/cases")
        os.mkdir(path+"/generated planes")
        os.mkdir(path+"/results")
        os.mkdir(path+"/cases")

        self.read_config(config_file)

        return None

    def read_config(self,file):
        with open(file,'r') as f:
            lines=[line for line in f.readlines()]
        lines=[line for line in lines if line[0]!="#" and line!="\n"]

        
        if lines[0].strip()!="TAIL CONFIG":
            print(f"\u001b[31m[Error]\u001b[0m Wrong config file type ({file}).")
            exit()
        lines=lines[1:]
        
        self.plane_file         = lines[0].split(": ")[1:][0].strip()
        self.wing_aerofoil      = lines[1].split(": ")[1:][0]
        self.elevator_aerofoil  = lines[2].split(": ")[1:][0]
        self.fin_aerofoil       = lines[3].split(": ")[1:][0]

        self.Xcg                = lines[4].split()[1]
        self.Ycg                = lines[5].split()[1]
        self.Zcg                = lines[6].split()[1]
        self.mass               = float(lines[7].split()[1])

        self.Xt_upper           = float(lines[8].split()[1])
        self.Xt_lower           = float(lines[9].split()[1])
        self.St_h_upper         = float(lines[10].split()[1])
        self.St_h_lower         = float(lines[11].split()[1])
        self.Ct_v               = float(lines[12].split()[1])
        self.steps              = 7

        self.sm_ideal           = float(lines[13].split()[1])
        self.tolerance          = float(lines[14].split()[1])
        self.config             = float(lines[15].split()[1])
        self.b_th               = lines[16].split()[1]

        self.threads            = int(lines[17].split()[1])
        
        if self.b_th!="NA":
            self.b_th=float(self.b_th)


        if self.Xt_lower==0 or self.St_h_lower==0:
            print("\u001b[31m[Error]\u001b[0m Input non-zero lower bound.")
            exit()
        
        if self.Xcg=="NA" and self.Ycg=="NA" and self.Zcg=="NA":
            self.calc_cg=True
        else:
            self.calc_cg=False

            self.Xcg=float(self.Xcg)
            self.Ycg=float(self.Ycg)
            self.Zcg=float(self.Zcg)

        if self.config!=0 and self.config!=1:
            print("\u001b[31m[Error]\u001b[0m Invalid tail configuration selected.")
            exit()
  
        self.St_h_range=np.linspace(self.St_h_lower,self.St_h_upper,self.steps)
        self.Xt_range=np.linspace(self.Xt_lower,self.Xt_upper,self.steps)

        return None

    def generate_planes(self):
        self.ref_plane=Plane(name="REF")
        self.ref_plane.read(self.plane_file)
        try:
            self.ref_plane.strip_section("Elevator")
        except KeyError:
            print("\u001b[33m[Warning]\u001b[0m No section 'Elevator' found. Check if geometry of generated planes looks correct.")
        try:
            self.ref_plane.strip_surface("Fin")
        except KeyError:
            print("\u001b[33m[Warning]\u001b[0m No surface 'Fin' found. Check if geometry of generated planes looks correct.")

        planes=[]

        self.Sw=self.ref_plane.Sw
        self.mac=self.ref_plane.mac
        self.b_w=self.ref_plane.b_w
        ARw=self.ref_plane.ARw
        ARh=ARw*2/3
        Xw_root=self.ref_plane.Xw_root
        Cw_root=self.ref_plane.Cw_root

        count=0
        for St_h in self.St_h_range:
            for Xt in self.Xt_range:
                St_h=float(St_h)
                Xt=Xt

                name=str(count)  #   Creates plane name
                plane=Plane(name=name)   #   Initializes new plane
                
                plane.Xt=Xt
                plane.Sw=self.Sw
                plane.Xw_root=Xw_root
                plane.Cw_root=Cw_root
                plane.St_h=St_h
                plane.ARh=ARh
                plane.mac=self.mac
                plane.b_w=self.b_w
                plane.sm_ideal=self.sm_ideal
                plane.tail_config=self.config
                plane.Ct_v=self.Ct_v

                if self.calc_cg==False:
                    plane.Xcg=self.Xcg

                mod_geom=copy.copy(self.ref_plane.file_str)

                if self.b_th!="NA" and self.config==1:   #   if span constraint used:
                    chord=St_h/self.b_th    #   Calculate chord based off span & area, not area & AR
                    span=self.b_th
                else:
                    chord=np.sqrt(St_h/plane.ARh)     #   Calculates h chord based on area & AR
                    span=np.sqrt(St_h*plane.ARh)      #   Calculates HTP span (Lunit)

                plane.b_th=span
                plane.c_t=chord

                plane.Lt=(plane.Xt+plane.c_t*0.25)-(plane.Xw_root+0.25*plane.Cw_root)
                if plane.Lt<=0:
                    print("\u001b[31m[Error]\u001b[0m Tail moment arm <=0. Increase Xt lower bound.")
                    exit()

                plane.St_v=plane.Ct_v*plane.Sw*plane.b_w/plane.Lt   #   Vertical tail sizing
                
                Zle=(plane.St_v)/(2*chord)         #   Calculates tip height (inverted v tail) (Lunit)
                plane.theta=np.rad2deg(np.arctan(Zle/(span/2)))

                if self.config==0:                
                    root=Section(Xt,0,0,chord,10,-1,self.elevator_aerofoil)    #   Defines root section (object)
                elif self.config==1:          
                    root=Section(Xt,0,Zle,chord,10,-1,self.elevator_aerofoil)

                tip=Section(Xt,span/2,0,chord,10,-2,self.elevator_aerofoil)    #   Defines tip section (object)
                mod_str=str(root)+str(tip)  #   Combines 2 sections to insert into reference plane

                for index,line in enumerate(mod_geom):
                    if line=="MARKER\n":
                        mod_geom.pop(index)    #   Removes marker
                        mod_geom.insert(index,mod_str) #   Inserts modified sections

                file_name=f"{plane.name}-{str(St_h)}{St_h}-{str(Xt)}Xt"
                plane.geom_file=f"generated planes/{file_name}.avl"
                
                with open(plane.geom_file,'w') as file:
                    file.write("".join(mod_geom))
                count+=1

                planes.append(plane)

        print("[Info] Planes generated.")
        self.planes=planes

        return planes

    def run(self):
        self.case=Case(self.Xcg,self.Ycg,self.Zcg,self.mass)
        self.case.write_stab_case()

        tasks=[(self.case,plane) for plane in self.planes]
        with ThreadPoolExecutor(max_workers=self.threads) as pool: #   Starts analysis on multiple threads
            list(tqdm(pool.map(self.stab_analysis,tasks),total=len(tasks),desc="Stability analysis"))

        tasks=[plane for plane in self.planes]
        with ThreadPoolExecutor(max_workers=self.threads) as pool: #   Starts post processing on multiple threads
            pool.map(self.calc_SM,tasks)

        return None

    def stab_analysis(self,tasks):
        case,plane=tasks

        cmd_str="load {0}\n".format(plane.geom_file)    #   Load plane
        cmd_str+="case {0}\n".format(case)  #   Load case
        cmd_str+="oper\n x\n"   #   Run analysis
        cmd_str+="st\n" #   View stability derivatives
        
        plane.results_file="results/"+plane.name+".txt"
        cmd_str+=plane.results_file+"\n"    #   Saves results
        
        avl_cmd(cmd_str)

        return None

    def calc_SM(self,tasks):
        plane=tasks
        if self.calc_cg==False:
            plane.calc_SM()
        else:
            plane.calc_Xcg_ideal()

        return None
    
    def func(self,data:np.ndarray,a:float,b:float,c:float,d:float)->np.ndarray:
        x=data[0]
        y=data[1]
        z=a*(x**b)*(y**c)+d
        return z

    def curve_fit(self,x:np.ndarray,y:np.ndarray,z:np.ndarray) ->np.ndarray:

        parameters, covariance = optimize.curve_fit(self.func,[x,y],z)

        return parameters

    def curve_fit_slice(self,planes) ->list[plt.figure,plt.axes]:

        St_hs=np.array([plane.St_h for plane in self.planes])
        Lts=np.array([plane.Lt for plane in self.planes])
        Xts=np.array([plane.Xt for plane in self.planes])
        SMs=np.array([plane.sm for plane in self.planes])

        def func_inv_const_z(x:np.ndarray,z:float,a:float,b:float,c:float,d:float) -> np.ndarray:
            y=np.exp((1/c)*np.log((z-d)/(a*x**b)))
            return y
        
        parameters=self.curve_fit(St_hs,Lts,SMs)
        St_h=np.linspace(self.St_h_lower,self.St_h_upper,100)
        Lt=func_inv_const_z(St_h,self.sm_ideal,*parameters)

        data=np.stack((St_hs,Lts,SMs),axis=-1)
        data_close=[]
        for item in data:
            if np.isclose(item[2],self.sm_ideal,atol=self.tolerance):
                data_close.append(item)
        data_close=np.array(data_close)

        St_v=self.Ct_v*self.Sw*self.b_w/Lt
        #print(self.Ct_v*self.Sw*self.b_w/11.58)
        #print(np.stack((St_h,0.9*self.mac*self.Sw/Lt),axis=-1))

        fig,ax=plt.subplots()

        ax.plot(Lt,St_h,color='k',linestyle='-',
            label=fr"Horizontal Tail"
        )

        ax.plot(Lt,St_v,color='k',linestyle='--',
            label=fr"Vertical Tail"
        )

        ax.set_ylabel(r"$St$ ($Lunit^2$)")
        ax.set_xlabel(r"$Lt$ ($Lunit$)")
        ax.legend()

        def Lt_to_Xt(x):
            return np.interp(x,Lts,Xts)
        
        def Xt_to_Lt(x):
            return np.interp(x,Xts,Lts)

        ax2=ax.secondary_xaxis('top',functions=(Lt_to_Xt,Xt_to_Lt))
        ax2.set_xlabel(r"Xt ($Lunits$)")

        return fig,ax
        
    def curve_fit_surface(self,x:list[float],y:list[float],z:list[float])->list[np.ndarray]:
        parameters=self.curve_fit(x,y,z)

        St_h_range=np.linspace(min(x),max(x),100)
        Lt_range=np.linspace(min(y),max(y),100)

        x2,y2=np.meshgrid(St_h_range,Lt_range)
        z2=self.func(np.array((x2,y2)),*parameters)

        return x2,y2,z2

    def results(self,display=True)->pd.DataFrame:
        """
        Plots results
        """
        
        # # for debugging
        # import pickle as pkl
        # with open("planes.pkl",'rb') as f:
        #     self.planes=pkl.load(f)
        # #

        if self.calc_cg==False:
    
            columns=["Plane ID","Static Margin","Xnp (Lunit)","Xt (Lunit)","Lt (Lunit)",
                    "Span (Lunit)","Chord (Lunit)","Angle (deg)","Sh (Lunit^2)","Sv (Lunit^2)","ARh"]
            solutions=[]
            for plane in self.planes:
                if np.isclose(plane.sm,plane.sm_ideal,atol=self.tolerance)==True:
                    solutions.append([
                        plane.name.split("-")[0],
                        plane.sm,
                        plane.np,
                        plane.Xt,
                        plane.Lt,
                        plane.b_th,
                        plane.c_t,
                        plane.theta,
                        plane.St_h,
                        plane.St_v,
                        plane.ARh,
                    ])
            
            solutions_df=pd.DataFrame(solutions,columns=columns)
            solutions_df=solutions_df.round(2)

            if self.config==0:
                solutions_df=solutions_df[["Plane ID","Static Margin","Xnp (Lunit)","Xt (Lunit)","Lt (Lunit)","Sh (Lunit^2)","Sv (Lunit^2)","ARh"]]
            
            #### Curve fit to get exact solutions ####
            x=[plane.St_h for plane in self.planes]
            y=[plane.Lt for plane in self.planes]
            z=[plane.sm for plane in self.planes]
            fig_cf,ax_ft=self.curve_fit_slice(self.planes)

            if len(solutions)==0:
                print("\n\u001b[33m[Warning]\u001b[0m No ideal configurations possible. Consider changing limits.")
            else:
                if display==True:
                    print("\nPossible configurations:\n")
                    print(solutions_df)
                    print("\nConsider refining limits around possible configurations.\n")

            if display==True:
                ##### Generated planes SM results (3D plot) #####

                fig=plt.figure()
                ax=fig.add_subplot(projection='3d')

                x2,y2,z2=self.curve_fit_surface(x,y,z)
                ax.plot_surface(x2,y2,z2,cmap=cm.jet)

                ax.scatter(x,y,z,color='k',depthshade=False)

                ax.set_xlabel("${St_h}$ (${Lunit^2}$)")
                ax.set_ylabel("${Lt}$ (${Lunit}$)")
                ax.set_zlabel("SM")

                fig.tight_layout()
                plt.show()

        elif self.calc_cg==True:

            columns=["Plane ID","Xcg (Lunit)","np (Lunit)","Static Margin"]
            solutions=[]
            for plane in self.planes:
                solutions.append([plane.name.split("-")[0],plane.Xcg,plane.np,self.sm_ideal])

            solutions_df=pd.DataFrame(solutions,columns=columns)
            solutions_df=solutions_df.round(2)

            if display==True:
                fig=plt.figure()
                ax=fig.add_subplot(projection='3d')

                x=[plane.St_h for plane in self.planes]
                y=[plane.Lt for plane in self.planes]
                z=[plane.np for plane in self.planes]

                ax.scatter(x,y,z)

                ax.set_xlabel("St_h (Lunit^2)")
                ax.set_ylabel("Xt")
                ax.set_zlabel(f"Xcg for SM={self.planes[0].sm_ideal}")
                
                print("\n",solutions_df)

                plt.show()

        return solutions_df

    def get_planes(self) -> list[Plane]:
        return self.planes

if __name__=="__main__":
    tail=AutoTail("projects/tail_MDDP_v0.config")
    tail.generate_planes()
    tail.run()
    tail.results()
