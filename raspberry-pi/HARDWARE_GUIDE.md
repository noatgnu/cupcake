# CUPCAKE Raspberry Pi 5 Hardware Selection Guide

## 🎯 Recommended Production Hardware Setup

### **Essential Components**

#### **1. Raspberry Pi 5 Board**
- **Recommended**: Raspberry Pi 5 8GB RAM
- **Minimum**: Raspberry Pi 5 4GB RAM
- **Why**: CUPCAKE requires significant memory for database operations and scientific data processing

#### **2. NVMe SSD Storage (CRITICAL for Production)**
- **Highly Recommended Options**:
  - Samsung 980 NVMe M.2 SSD (500GB) - ~$35-45
  - WD Blue SN570 NVMe M.2 SSD (500GB) - ~$30-40  
  - Crucial P3 NVMe M.2 SSD (500GB) - ~$25-35
- **Size**: 256GB minimum, 500GB+ recommended for production
- **Why**: 10-20x faster than SD cards, essential for database reliability

#### **3. M.2 NVMe HAT**
- **Official**: Raspberry Pi M.2 HAT+ - ~$12
- **Alternative**: Pineberry Pi HatDrive! Top - ~$25
- **Alternative**: Geekworm X1013 - ~$20
- **Why**: Provides stable M.2 connection and heat dissipation

#### **4. Power Supply**
- **Required**: Official Raspberry Pi 5 USB-C PSU (5V 5A/25W) - ~$12
- **Alternative**: Any high-quality 5V 5A USB-C supply with Pi 5 compatibility
- **Why**: Pi 5 with NVMe requires more power than previous models

#### **5. Cooling Solution**
- **Recommended**: Active cooling fan + heatsink combo
  - Official Raspberry Pi Active Cooler - ~$5
  - Argon NEO 5 M.2 Case (includes cooling) - ~$35
- **Why**: NVMe and continuous operation generate heat

### **Total Cost Breakdown (Production Setup)**
- Raspberry Pi 5 8GB: $80
- Samsung 980 500GB NVMe: $40
- M.2 HAT+: $12
- Official PSU: $12
- Active Cooler: $5
- microSD (32GB, temp setup): $8
- Case (optional): $15
- **Total**: ~$172

## 📊 Storage Performance Comparison

| Storage Type | Read Speed | Write Speed | Random IOPS | Reliability | Cost |
|-------------|------------|-------------|-------------|-------------|------|
| **NVMe SSD** | 3,500 MB/s | 3,000 MB/s | 500K+ | Excellent | $$ |
| High-End SD | 200 MB/s | 90 MB/s | 4K | Poor | $ |
| USB 3.0 SSD | 400 MB/s | 300 MB/s | 50K | Good | $$ |
| Standard SD | 95 MB/s | 60 MB/s | 1K | Very Poor | $ |

### **Database Performance Impact**
- **NVMe**: Sub-second query responses, reliable concurrent access
- **SD Card**: 5-10x slower queries, potential corruption under load
- **USB SSD**: 2-3x slower than NVMe, good compromise option

## 🏗️ Hardware Assembly Order

### **Step 1: NVMe Setup**
1. Install NVMe SSD into M.2 HAT
2. Attach HAT to Pi 5 GPIO header
3. Secure with provided standoffs
4. Connect any additional cooling

### **Step 2: Initial Boot Preparation**
1. Flash CUPCAKE image to temporary SD card (32GB+)
2. Insert SD card into Pi 5
3. Connect ethernet cable
4. Connect power supply

### **Step 3: NVMe Migration**
1. Boot from SD card
2. Run NVMe setup script: `sudo /opt/cupcake/scripts/setup-nvme.sh`
3. Allow system to migrate to NVMe (15-20 minutes)
4. Shutdown and remove SD card
5. Reboot from NVMe

## 🔧 Case Options for Different Use Cases

### **Laboratory Bench Use**
- **Open Frame**: Raspberry Pi Foundation Case - $5
  - Pros: Easy access, good cooling
  - Cons: Less protection, no built-in cooling

- **Desktop Case**: Argon NEO 5 M.2 - $35
  - Pros: Built-in M.2 slot, excellent cooling
  - Cons: Higher cost

### **Rack Mount/Server Use**
- **1U Rack Case**: Various options available
- **DIN Rail Mount**: For control cabinet installation
- **19" Rack Adapter**: For standard server racks

### **Portable/Field Use**
- **Pelican Case**: Weather-resistant, shock-proof
- **Aluminum Case**: Heat dissipation, EMI shielding
- **Battery Pack**: UPS functionality for field work

## ⚡ Power Considerations

### **Power Requirements**
- **Pi 5 Base**: 5-8W
- **NVMe SSD**: 2-4W
- **Cooling Fan**: 0.5-1W
- **Total Peak**: ~12W
- **Continuous**: ~8W average

### **UPS Options**
- **Waveshare UPS HAT**: Built-in battery backup
- **External UPS**: APC Back-UPS or similar
- **Power Bank**: High-capacity USB-C power banks

## 🌡️ Thermal Management

### **Operating Temperatures**
- **Pi 5 CPU**: 85°C max (throttles at 80°C)
- **NVMe SSD**: 70°C max recommended
- **Ambient**: 0-40°C for reliable operation

### **Cooling Solutions**
1. **Passive**: Heatsinks only (adequate for <25°C ambient)
2. **Active**: Fan + heatsinks (recommended for continuous operation)
3. **Liquid**: Custom loops (overkill for most applications)

## 🔌 Connectivity Options

### **Network**
- **Ethernet**: Gigabit built-in (recommended for stability)
- **WiFi 6**: 2.4/5GHz built-in (backup connection)
- **Cellular**: USB dongles for remote locations

### **Expansion**
- **USB 3.0**: 2x ports for external devices
- **USB 2.0**: 2x ports for peripherals
- **GPIO**: 40-pin for custom hardware integration
- **Camera/Display**: CSI/DSI connectors available

## 📋 Pre-Purchase Checklist

### **Before Ordering**
- [ ] Confirm Pi 5 compatibility of all components
- [ ] Calculate total power requirements
- [ ] Plan physical mounting/case requirements  
- [ ] Consider network connectivity needs
- [ ] Factor in local availability and shipping

### **Quality Verification**
- [ ] Purchase from authorized distributors
- [ ] Check component compatibility matrices
- [ ] Verify warranty coverage
- [ ] Test components individually before assembly

## 🚀 Performance Expectations

### **With Recommended NVMe Setup**
- **Boot Time**: 15-20 seconds
- **Database Queries**: <500ms typical
- **File Uploads**: 50-100 MB/s
- **Concurrent Users**: 5-10 users smoothly
- **Uptime**: 99%+ with proper cooling and UPS

### **With SD Card (Not Recommended for Production)**
- **Boot Time**: 45-60 seconds
- **Database Queries**: 2-5 seconds
- **File Uploads**: 10-20 MB/s
- **Concurrent Users**: 2-3 users maximum
- **Uptime**: Variable, corruption risk

## ⚠️ Important Notes

### **DO NOT Use for Production**
- Consumer-grade SD cards
- USB 2.0 external drives
- Generic power supplies <5A
- Passive cooling in warm environments

### **Laboratory Environment Considerations**
- **Electromagnetic interference**: Use shielded cases if needed
- **Chemical resistance**: Consider appropriate enclosures
- **Vibration isolation**: Secure mounting for sensitive equipment areas
- **Temperature monitoring**: Implement alerts for thermal events

### **Maintenance Schedule**
- **Monthly**: Check temperatures and fan operation
- **Quarterly**: Clean dust from cooling components
- **Annually**: Verify SSD health and backup integrity
- **As needed**: Update firmware and software

This hardware guide ensures optimal performance and reliability for CUPCAKE in production laboratory environments.